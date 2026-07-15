**Backend:** Python, FastAPI

**Database (structured):** SQLite via SQLAlchemy — Documents, Versions, Nodes, Selections, SelectionNodes

**Database (unstructured):** JSON file store (justify: Mongo adds infra overhead for solo/local dev, JSON sufficient for LLM output blobs keyed by selection_id+hash — swappable for Mongo later w/o schema change) — or Mongo Atlas free tier if want closer to spec

**LLM Provider:** Groq (free tier, fast inference) — Gemini as fallback option

**Key Libraries:** Pydantic (validation), python-frontmatter or manual regex parser (markdown), hashlib (content hash), pytest (tests), httpx (LLM calls)

**Hosting:** local/dev only — not required per spec ("no UI, no deploy" implied — confirm not required, focus API correctness)

**Env Vars:** `GROQ_API_KEY`, `DATABASE_URL` (default sqlite local), `LLM_MODEL_NAME`

**Constraints:** No auth. No generic parser (target only CT-200 doc's known irregularities). No frontend.

**Folder structure:**

```
/app
  /parser        - markdown → tree logic
  /models        - SQLAlchemy models
  /schemas       - Pydantic schemas
  /api           - FastAPI routers (browse, selections, generate, retrieve)
  /llm           - prompt + call + validation/retry
  /storage       - JSON/Mongo adapter for generations
  /versioning    - matching + diff + hash logic
/tests
  /test_parser.py
  /test_versioning.py
  /test_llm_validation.py
/data
  ct200_manual.md
  ct200_manual_v2.md
README.md
APPROACH.md
```

