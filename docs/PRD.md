**App Name:** CardioTrack QA Trace

**Tagline:** Versioned document tree + AI test-case generator with built-in staleness detection.

**Problem:** Regulated docs (medical device manuals) change over time. Test cases/artifacts generated from old text silently go stale when doc updates. No system tracks this — teams ship tests against outdated requirements without knowing it.

**Target User:** QA engineer at medtech co. Needs to browse spec doc, pick sections, generate test-case drafts via LLM, and trust that stale generations get flagged when source doc changes.

**Core Features (Must Have):**

- Parse markdown manual → hierarchical node tree, persisted
- Re-ingest new doc version, match nodes v1→v2, flag changed
- Browse: list sections, get node by ID, search, diff-check
- Named version-pinned selections (set of node+version pairs)
- LLM generation: selection → 3-5 test case ideas, stored w/ content hash link
- Staleness check at retrieval (hash compare vs latest version)
- Retrieval API by selection ID / node ID, staleness visible

**Nice to Have:** none — assignment explicit "don't over-build."

**Out of Scope:** Auth/accounts, generic markdown parser, auto-regen of stale cases, UI/frontend.

**User Stories:**

- As QA engineer, I want to browse manual by section, so I find relevant spec fast.
- As QA engineer, I want to select sections and generate test ideas, so I skip manual drafting.
- As QA engineer, I want to know if a generated test case is stale, so I don't ship tests against outdated spec.
- As QA engineer, I want old selections to resolve to original text even after re-ingestion, so historical generations stay meaningful.

**Success Metrics:** All 7 API capability groups functional end-to-end; 3+ parser tests pass on real irregularities; staleness flag correctly differentiates changed vs unchanged nodes across v1→v2 diff.