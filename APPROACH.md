# Approach

This project is built around one assumption: the manual's numbered headings are meaningful enough to become stable IDs. Once I trusted that, the rest of the shape got simpler. Parse the document into numbered nodes, store every ingest as a new version, let selections point at concrete node rows, and compare hashes later to see whether old generated tests might be stale.

That assumption is useful, but not magic. The fixture had enough weirdness to make that clear.

## Data model

The database has `documents`, `document_versions`, `nodes`, `selections`, and `selection_nodes`.

`documents` is just the named thing being tracked. `document_versions` stores each ingest of that document, with a monotonically increasing `version_number`. Nodes are version-specific rows. That matters a lot: node `4.2` in v1 and node `4.2` in v2 are separate database rows, even though they share a `logical_id`.

`nodes` stores the parsed tree:

- `logical_id` is the path key, like `4.2`.
- `path` is currently the same value, kept because the schema asked for it and because it leaves room for display/path variations later.
- `parent_id` is a self-reference for the tree.
- `content_hash` is a SHA-256 hash of the node body.
- `order_index` comes from numeric order, not file order.

`selections` and `selection_nodes` are deliberately small. A selection stores a list of exact `node_id` values. Since each node row belongs to one document version, this makes selections version-pinned without a separate pinning system. That was one of the nicer parts of the model.

Generations are in `data/generations.json`, not SQL. Each record stores the selection ID, the node snapshot at generation time, the prompt, the raw LLM response, parsed test cases, status, and timestamp. The snapshot is the important bit for Phase 9: `{node_id, logical_id, content_hash}` is enough to compare the generated output against the latest document later.

## Tree parsing decisions

The parser reads Markdown headings, extracts numeric prefixes, and builds an in-memory tree before anything touches the database. I made numeric prefixes the source of truth for hierarchy and sibling order. Markdown heading depth and file order are treated as hints at best.

Here are the actual irregularities from `data/ct200_manual.md` and how the parser handles them:

- The document title has no numeric prefix: `# CardioTrack CT-200 Home Blood Pressure Monitor ...`. I use it as the synthetic root node heading, not as a numbered section.

- There is pre-heading content: `<!-- TODO: confirm with regulatory -->`. It gets attached to the synthetic root body. This was worth testing because dropping preamble text silently would be a bad habit.

- That pre-heading content is an HTML comment. The parser preserves it verbatim in the root body.

- `2.1.1.1 Battery Life Under Typical Use` uses four `#` markers, but the numeric prefix implies level 4, which would normally be five Markdown markers if the document title is counted separately. The parser trusts `2.1.1.1`, not the Markdown depth.

- `3.2 Cuff Inflation Sequence` uses four `#` markers even though the numeric prefix says it is a level-2 child of `3`. Again, numeric prefix wins. This one was annoying to get right because a Markdown-depth parser would attach it under `3.1`, which is just wrong for this document.

- Section `3.4` appears before `3.3` in the file. Sibling order is sorted numerically, so `3.3` comes before `3.4` in the parsed tree.

- The heading title `Error Codes` appears twice, at `4.2` and `7.1`. They become two distinct nodes. Matching by title would be broken here.

- Section `2.1` contains a Markdown table. Table rows stay in the body. Only Markdown heading lines are treated as section boundaries.

- Section `3.3` contains an ordered list with items `1.` through `5.`. Those stay in the body too. They are not headings because they do not start with `#`.

- Section `4.2` contains another Markdown table. Same handling: keep it as body text.

- `2.1.1.1` implies a parent `2.1.1`, but that heading does not exist. The parser attaches it to the nearest existing ancestor, `2.1`, and logs a `missing_intermediate_parent` irregularity.

The parser tests focus on the places most likely to regress: numeric hierarchy beating Markdown depth, numeric order beating file order, duplicate headings staying distinct, preamble content staying on root, and the missing-intermediate-parent fallback.

## Version matching

Versions are matched by `logical_id`, which is just the numbered heading path. So `4.2` in v1 and `4.2` in v2 are considered the same logical section.

I picked that because the source document is already organized around numbered headings, and those numbers survive ordinary body edits and insertions. The v2 fixture is a good example: `5.3 Data Export` is inserted without disturbing `5.1` or `5.2`, and body edits to `3.2` and `4.2` are easy to detect by comparing hashes for the same `logical_id`.

The failure modes are real:

- If a section is renumbered but the text barely changes, this system treats it as removed plus inserted.
- If a section is deleted and a new unrelated section later reuses the same number, this system treats it as the same logical node.
- If the author stops numbering headings consistently, the parser can only do so much. Unnumbered structural sections are currently not merged into a nearby node in a clever way.

I would not use title matching as the fallback without more thought, because `4.2 Error Codes` and `7.1 Error Codes` are already a counterexample in the fixture.

## LLM generation

The prompt takes selected nodes as `{logical_id, heading, body}` and asks for 3 to 5 QA test case ideas. The output contract is intentionally narrow:

```json
{
  "test_cases": [
    {
      "title": "short descriptive title",
      "steps": ["step 1", "step 2"],
      "expected_result": "observable expected result"
    }
  ]
}
```

The prompt explicitly says: return only valid JSON, no Markdown fences, no prose. That sounds blunt, but it is there because the next step is `json.loads` plus Pydantic validation. A polite paragraph before the JSON is still a failure for this API.

The retry policy is simple: try the LLM call up to 3 total attempts. If parsing or validation fails every time, store a failed generation record with the raw response and errors. Do not invent empty test cases, and do not pretend the operation succeeded.

Duplicate submissions always create a new generation record. I went with that because LLM output is non-deterministic, and overwriting would make it hard to explain what happened later. The Phase 9 list endpoint can show every attempt. This is noisier, but safer for auditability.

The Groq client reads `GROQ_API_KEY` and defaults to `llama-3.1-8b-instant`. Automated tests use a mocked LLM client to keep them deterministic and fast, covering both valid responses and malformed/wrong-shape failure paths. I also verified the real Groq integration manually end-to-end with `GROQ_API_KEY` configured — confirmed structured output parsing, retry behavior, and staleness detection all work correctly against live model output.

## Staleness

A generation stores a snapshot of the nodes used at generation time:

```json
[
  {"node_id": 16, "logical_id": "4.2", "content_hash": "..."},
  {"node_id": 11, "logical_id": "3.2", "content_hash": "..."}
]
```

At retrieval time, the API finds the latest version for the document, looks up each snapshot `logical_id`, and compares the latest node's `content_hash` to the saved hash. If they differ, that node is stale. If the logical ID no longer exists in the latest version, it is marked `removed`. The generation-level `is_stale` is true if any selected node is changed or removed.

This is binary. It catches change, not meaning.

That means `4.3` changing wording from `E1-E5` to `E1-E6` is treated the same kind of stale as `3.2` changing inflation increments from `40 mmHg` to `30 mmHg`. The second one is obviously more likely to invalidate generated tests. The hash does not know that. It just says "different body text." For this assignment, that is acceptable and easy to reason about, but it is not severity analysis.

## What I would do differently with more time

I would move generations into SQL. A JSON file is fine for a small demo, but it is the first thing I would replace because concurrent writes and querying will get awkward quickly.

I would add real upload handling for ingest. Right now the API takes a `file_path`, partly because the early FastAPI upload route would have needed `python-multipart`, which was not in the dependency list. File paths were enough for the local flow, but they are not a real external API.

I would make parser irregularities first-class database records. Right now they are returned during ingest and logged, but they are not persisted. They are useful enough that I would want to inspect them later.

I would also add a semantic diff layer for staleness. Hashes are a good tripwire, but they cannot tell "typo fixed" from "safety threshold changed." Even a lightweight classifier or rules around numbers and units would be a big improvement.

Finally, I would put more tests around the API endpoints. The parser tests are the strongest part right now. The later phases were mostly verified end-to-end with curl/TestClient scripts.

## Decision log

**1. What's the one part of this system most likely to silently give wrong results without erroring? How would you catch it?**

Logical-ID matching is the risky part. If a document author renumbers a section or reuses a deleted number for unrelated content, the API can produce a plausible but wrong match; I would catch this by adding a secondary similarity check on heading/body and flagging low-similarity matches for review.

**2. Where did you choose simplicity over correctness because of time, and what would break first if this went to production as-is?**

The JSON file generation store is the clearest shortcut. It was fast and readable, but concurrent generation requests could race, and filtering generations by selection or node will get clumsy as the file grows.

**3. Name one input you did not handle, and what your system does when it sees it.**

I did not build true file upload ingestion. The endpoint accepts a `file_path` value, either in JSON or form data, and reads that path from the server's filesystem; if an external client sends actual multipart file content, the API does not save or parse that uploaded file. The gap is the endpoint design, not a missing dependency.
