# CT Doc Trace

This is a small FastAPI service for parsing a numbered Markdown manual, storing versioned section trees, selecting specific version-pinned nodes, generating QA test case ideas from those selections, and later checking whether those generated cases are stale after a new document version is ingested.

The sample data is the CT-200 manual in `data/ct200_manual.md` and `data/ct200_manual_v2.md`.

## Setup

Create a virtual environment and install dependencies:

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

Create a local `.env` file:

```bash
cp .env.example .env
```

Then edit `.env`:

```text
GROQ_API_KEY=your_real_groq_api_key_here
DATABASE_URL=sqlite:///./data/app.db
LLM_MODEL_NAME=llama-3.1-8b-instant
```

`GROQ_API_KEY` is only needed for the LLM generation endpoint. Everything else works without it.

## Run the server

```bash
venv/bin/python -m uvicorn main:app --reload
```

The API will be at:

```text
http://127.0.0.1:8000
```

Tables are created on startup from the SQLAlchemy models. There is no migration tool yet.

## Run tests

```bash
venv/bin/python -m pytest
```

## Full v1 to v2 staleness flow

These commands assume the server is running on port `8000` and use the default SQLite DB in `data/app.db`.

If you want a clean local run:

```bash
rm -f data/app.db data/generations.json
```

Start the server again after removing the DB.

### 1. Ingest v1

```bash
curl -s -X POST http://127.0.0.1:8000/documents/ingest \
  -H 'Content-Type: application/json' \
  -d '{"name":"CT-200 Manual","file_path":"data/ct200_manual.md"}' \
  | python3 -m json.tool
```

You should see `document.id` as `1`, `version_number` as `1`, and `node_count` as `28`.

### 2. Find the v1 node IDs for sections 4.2 and 3.2

```bash
sqlite3 -header -column data/app.db \
  "SELECT n.id, n.logical_id, n.heading, v.version_number
   FROM nodes n
   JOIN document_versions v ON v.id = n.version_id
   WHERE v.document_id = 1
     AND v.version_number = 1
     AND n.logical_id IN ('4.2', '3.2')
   ORDER BY n.logical_id;"
```

In the clean fixture run these are usually:

```text
3.2 -> node id 11
4.2 -> node id 16
```

If your DB already had data, use the IDs printed by the query.

### 3. Create a selection pinned to those v1 nodes

```bash
curl -s -X POST http://127.0.0.1:8000/selections \
  -H 'Content-Type: application/json' \
  -d '{"name":"v1 alarm and inflation checks","node_ids":[16,11]}' \
  | python3 -m json.tool
```

The selection stores concrete `node_id` values. Since node rows belong to one document version, this pins the selection to v1 automatically.

### 4. Generate QA test case ideas

```bash
curl -s -X POST http://127.0.0.1:8000/selections/1/generate \
  | python3 -m json.tool
```

This calls Groq, validates the JSON response, and appends a record to `data/generations.json`.

Capture the generation ID:

```bash
GEN_ID=$(python3 - <<'PY'
import json
with open("data/generations.json", encoding="utf-8") as f:
    print(json.load(f)[-1]["generation_id"])
PY
)
echo "$GEN_ID"
```

### 5. Ingest v2 under the same document

```bash
curl -s -X POST http://127.0.0.1:8000/documents/1/ingest \
  -H 'Content-Type: application/json' \
  -d '{"file_path":"data/ct200_manual_v2.md"}' \
  | python3 -m json.tool
```

You should see `version_number` as `2`, `node_count` as `29`, and `5.3` listed as inserted. Sections `3.2` and `4.2` should show as changed.

### 6. Retrieve the generation and check staleness

```bash
curl -s "http://127.0.0.1:8000/generations/$GEN_ID" \
  | python3 -m json.tool
```

The `staleness.is_stale` value should be `true`. The per-node details should show:

```text
4.2 -> changed
3.2 -> changed
```

with the old saved `content_hash` from generation time and the latest v2 `content_hash`.

You can also list by selection:

```bash
curl -s "http://127.0.0.1:8000/generations?selection_id=1" \
  | python3 -m json.tool
```

Or by a pinned node ID:

```bash
curl -s "http://127.0.0.1:8000/generations?node_id=16" \
  | python3 -m json.tool
```

## A few useful browse calls

Top-level sections for latest version:

```bash
curl -s "http://127.0.0.1:8000/documents/1/sections" | python3 -m json.tool
```

Top-level sections for v1:

```bash
curl -s "http://127.0.0.1:8000/documents/1/sections?version=1" | python3 -m json.tool
```

Search latest version:

```bash
curl -s "http://127.0.0.1:8000/documents/1/search?q=bluetooth" | python3 -m json.tool
```

Diff a node between versions:

```bash
curl -s "http://127.0.0.1:8000/documents/1/nodes/4.2/diff?from=1&to=2" | python3 -m json.tool
```

## Current rough edges

The ingest endpoint accepts a local `file_path` JSON field. I originally avoided real multipart upload handling because `python-multipart` was not in the dependency set, and the file-path path was enough for this assignment flow.

The generation store is a JSON file, not a real database table. That was intentional for the phase plan, but it is obviously not where I would leave it for concurrent writes.
