# Approach

The whole project rests on one bet: the manual's numbered headings (4.2, 3.2.1, etc.) are stable enough to use as IDs. Once I committed to that, everything else fell into place pretty naturally — parse the doc into numbered nodes, treat every ingest as a new version, let selections point at actual node rows, and compare hashes later to catch staleness.

That bet mostly paid off, but it's not bulletproof, and the fixture document made sure I found the edges.

## Data model

Five tables: `documents`, `document_versions`, `nodes`, `selections`, `selection_nodes`.

`documents` just tracks the named thing. `document_versions` holds one row per ingest, with a `version_number` that only goes up. Nodes are version-specific — node `4.2` in v1 and node `4.2` in v2 are two different rows in the database, even though they share a `logical_id`. That distinction turned out to matter a lot for how everything downstream works.

Fields on `nodes`:

- `logical_id` — the numbered path, e.g. `4.2`
- `path` — currently identical to `logical_id`; I kept it separate mostly because the schema called for it and it leaves room to diverge later
- `parent_id` — self-referencing FK for the tree
- `content_hash` — SHA-256 of the body text
- `order_index` — derived from the numeric prefix, not file order

`selections` and `selection_nodes` are intentionally minimal. A selection just stores a list of concrete `node_id`s. Since a node row belongs to exactly one version, selections end up version-pinned for free — no separate pinning mechanism needed. Honestly one of the parts of this design I'm happiest with.

Generations live in `data/generations.json`, not in SQL. Each record has the selection ID, a snapshot of the nodes used, the prompt, the raw LLM response, the parsed test cases, a status, and a timestamp. The snapshot — `{node_id, logical_id, content_hash}` — is what makes staleness checking possible later, without needing to touch SQL at all.

## Parsing decisions

The parser reads markdown headings, pulls out numeric prefixes, and builds a tree in memory before anything hits the database. Numeric prefixes are the source of truth for both hierarchy and sibling order — markdown heading depth (`#`, `##`, etc.) and file order are just hints, and get overridden when they disagree with the numbers.

Here's what actually showed up in `ct200_manual.md` and how I handled each case:

- **No numeric prefix on the title.** `# CardioTrack CT-200 Home Blood Pressure Monitor...` isn't a numbered section, so it becomes the synthetic root node's heading instead.

- **Content before any heading.** There's a stray `<!-- TODO: confirm with regulatory -->` before section 1 even starts. I attach it to the root node's body rather than dropping it — losing content silently felt like exactly the kind of bug this assignment was trying to surface.

- **That pre-heading content happens to be an HTML comment.** Kept it verbatim in the root body, no special-casing.

- **`2.1.1.1 Battery Life Under Typical Use`** is written with four `#` markers, but its numeric prefix says it's four levels deep. A depth-based parser would get this wrong. I trust the number, not the `#` count.

- **`3.2 Cuff Inflation Sequence`** — same problem, four `#` markers but the number says it should be a level-2 child of `3`. This one actually tripped me up for a bit, because a naive depth-based parser attaches it under `3.1` instead of `3`, which is just wrong.

- **`3.4` appears in the file before `3.3`.** Sibling ordering is done by sorting the numeric path, not by reading order, so `3.3` still ends up before `3.4` in the tree.

- **"Error Codes" is used as a heading twice** — once at `4.2`, once at `7.1`. These become two separate nodes with separate IDs. This is the case that ruled out title-based matching for me later.

- **Markdown tables inside section bodies** (2.1 and 4.2). These stay as plain body text — only lines starting with `#` count as headings, so table rows never get mistaken for structure.

- **An ordered list (`1.` through `5.`) inside section 3.3.** Same reasoning — no leading `#`, so it stays in the body instead of being parsed as sub-headings.

- **`2.1.1.1` implies a parent `2.1.1` that doesn't exist.** The parser falls back to the nearest real ancestor, `2.1`, and logs it as a `missing_intermediate_parent` irregularity instead of silently failing or crashing.

The unit tests target exactly these regressions: numeric hierarchy winning over markdown depth, numeric order winning over file order, duplicate headings staying distinct, preamble content landing on the root, and the missing-parent fallback.

## Version matching

Nodes are matched across versions by `logical_id` — so `4.2` in v1 and `4.2` in v2 are treated as the same logical section, just two different rows.

I went with this because the document is already organized around numbered headings, and those numbers tend to survive normal edits and insertions. The v2 fixture backs this up: `5.3 Data Export` gets inserted without touching `5.1` or `5.2` at all, and edits to `3.2` and `4.2` show up cleanly as hash mismatches on the same `logical_id`.

Where it breaks:

- If a section gets renumbered but the text barely changes, the system sees it as one section removed and a new one inserted — not a rename.
- If a section is deleted and a later section reuses the same number for something unrelated, the system will treat them as the same logical node, which is wrong.
- If headings stop being numbered consistently somewhere in the document, there's no clever recovery — it just does the best it can with the intermediate-parent fallback.

I deliberately didn't fall back to title matching, because the fixture already disproves it — `4.2 Error Codes` and `7.1 Error Codes` share a title but are clearly different sections.

## LLM generation

The prompt sends selected nodes as `{logical_id, heading, body}` and asks for 3–5 QA test case ideas. The expected output shape is narrow on purpose:

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

The prompt is blunt about format — only valid JSON, no code fences, no explanatory text before or after. That's not me being fussy for no reason: the next step is `json.loads()` followed by Pydantic validation, and a friendly paragraph before the JSON breaks both.

Retry logic: up to 3 attempts total. If every attempt fails to parse or validate, the system stores a failed generation record with the raw response and the errors attached — it does not fabricate empty test cases or pretend something succeeded when it didn't.

If the same selection gets submitted twice, I always create a new generation record rather than overwriting or deduping. LLM output isn't deterministic, so overwriting would make it harder to reconstruct what actually happened on a given attempt. It's noisier, but you can list every generation for a selection and see the full history, which felt like the safer default for something meant to support QA auditability.

The Groq client reads `GROQ_API_KEY` and defaults to `llama-3.1-8b-instant`. The automated test suite mocks the LLM client so it stays fast and deterministic, and covers both the happy path and malformed/wrong-shape failures. I also ran the real integration manually with a live `GROQ_API_KEY` — confirmed the structured output parsing, retry behavior, and staleness detection all work correctly against actual model responses, not just mocks.

## Staleness

Every generation stores a snapshot of the nodes it was built from:

```json
[
  {"node_id": 16, "logical_id": "4.2", "content_hash": "..."},
  {"node_id": 11, "logical_id": "3.2", "content_hash": "..."}
]
```

At retrieval time, the API looks up the latest version of the document, finds each snapshot's `logical_id` in that version, and compares content hashes. Different hash → stale. Missing `logical_id` entirely → marked removed. The generation-level `is_stale` flag is true if any node in the snapshot is either changed or removed.

It's a binary check. It tells you something changed, not what changed or how much it matters.

Concretely: if section `4.3` gets a wording tweak from "E1–E5" to "E1–E6," that's flagged exactly the same way as `3.2`'s inflation increment changing from 40 mmHg to 30 mmHg — even though one is a minor wording update and the other could invalidate an entire generated test case. The hash just sees "the text is different." For this assignment that tradeoff felt fine — it's simple, predictable, and easy to reason about — but it's not real severity analysis, and I'd want to fix that before trusting it in an actual regulated pipeline.

## What I'd do differently with more time

Move generations into SQL. The JSON file works fine for a demo, but it's the first thing that breaks under concurrent writes or any real querying needs.

Add real file upload handling. Right now ingest takes a `file_path` and reads from the server's own filesystem — partly because wiring up multipart uploads properly needed `python-multipart`, which wasn't in my dependency list at the time. It's fine for local testing but isn't how a real external API should take input.

Persist parser irregularities instead of just returning them at ingest time. Right now they're logged and returned in the response, but they don't live anywhere afterward — I'd want to be able to query them later.

Add a semantic diff layer for staleness instead of relying on raw hash comparison. Hashing is a good tripwire but has no concept of "typo fix" versus "safety-critical threshold change." Even simple rules around numbers and units would go a long way.

Write more tests around the actual API endpoints. The parser tests are the strongest part of the suite right now — most of the later phases (versioning, selections, generation, staleness) were verified end-to-end manually with curl and TestClient rather than with a comprehensive automated suite.

## Decision log

**1. What's the one part of this system most likely to silently give wrong results without erroring? How would you catch it?**

Logical-ID matching. If a section gets renumbered, or a deleted number gets reused for something unrelated, the system will produce a confident, well-formed match that's just wrong — no error, no warning. I'd catch this by adding a secondary similarity check between the old and new body text whenever a logical_id "disappears" and a new one "appears" in the same diff, and flagging low-similarity pairs for a human to check.

**2. Where did you choose simplicity over correctness because of time, and what would break first if this went to production as-is?**

Storing generations as a JSON file instead of a real table. It was fast to build and easy to inspect, but it has no protection against concurrent writes, and filtering by selection or node gets slower and messier as the file grows. That's the first thing that would fall over under any real load.

**3. Name one input you did not handle, and what your system does when it sees it.**

Real file uploads. The ingest endpoint only accepts a `file_path` string (JSON or form field) and reads that path off the server's own disk. If a client sends actual multipart file bytes instead, nothing saves or parses them — the endpoint simply isn't built to accept that input shape. This is a deliberate scope choice from early on, not something the app fails at silently.