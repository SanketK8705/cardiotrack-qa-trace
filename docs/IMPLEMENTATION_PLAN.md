**Phase 1 — Setup:** repo init, FastAPI skeleton, folder structure, SQLAlchemy engine, env vars, first commit.

**Phase 2 — Parser (no DB yet):** write parser reading raw md → in-memory tree. Print/inspect against v1 file manually. Log every irregularity found. Commit.

**Phase 3 — Parser tests:** write 3+ tests targeting: heading-depth-vs-numeric-prefix mismatch (3.2/3.4/3.3 case), duplicate heading same title diff parent (4.2 vs 7.1 "Error Codes"), orphan pre-heading content (TODO comment). Fix parser til green. Commit.

**Phase 4 — DB models + ingest v1:** SQLAlchemy models per schema above, ingest endpoint, persist tree. Commit.

**Phase 5 — Versioning + ingest v2:** match by `logical_id` (path-based — numbered headings make this reliable; justify + note failure mode: breaks if section renumbered without heading text change). Hash-diff to flag changed nodes. Handle insertion case (5.3 new in v2). Commit.

**Phase 6 — Browse API:** list/get/search/diff endpoints. Commit.

**Phase 7 — Selections API:** create selection, pin node+version pairs. Commit.

**Phase 8 — LLM generation:** prompt design, Groq call, Pydantic-validate structured response, retry policy (max 2 retries → fail explicit), store to JSON/Mongo linked to content_hash snapshot. Decide + implement duplicate-submission policy. Commit.

**Phase 9 — Staleness + retrieval API:** hash-compare logic, expose via GET generations endpoint. Commit.

**Phase 10 — Docs:** README (setup, run, v1→v2 trigger steps), [APPROACH.md](http://APPROACH.md) (parser irregularities+how found, matching strategy+failure modes, LLM retry design, decision log 3 answers, what you'd improve). Commit.

**Phase 11 — Demo artifact:** curl script or Postman collection proving full flow: ingest v1 → select → generate → ingest v2 → retrieve → see staleness flag. Commit.

**Done criteria:** all endpoints functional, 3+ parser tests passing, full v1→staleness flow demonstrable via script, approach doc answers all 3 decision-log questions with real reasoning tied to this doc's actual irregularities (not generic).