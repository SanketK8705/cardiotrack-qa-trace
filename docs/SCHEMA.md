**Table: documents**  
`id (int, pk), name (text), created_at (timestamp)`

**Table: document_versions**  
`id (int, pk), document_id (FK→documents.id), version_number (int), ingested_at (timestamp), source_filename (text)`

**Table: nodes**  
`id (int, pk), version_id (FK→document_versions.id), logical_id (text — stable path key e.g. "4.2", used for cross-version matching), heading (text), level (int), path (text — e.g. "4.2" or "2.1.1.1"), body (text), parent_id (FK→nodes.id, nullable), content_hash (text, sha256 of body), order_index (int — numeric-prefix-derived, not file-order)`

**Table: selections**  
`id (int, pk), name (text), created_at (timestamp)`

**Table: selection_nodes**  
`id (int, pk), selection_id (FK→selections.id), node_id (FK→nodes.id) — pins exact version's node row`

**Relationships:**

- `document_versions.document_id → documents.id` (many-to-one)
- `nodes.version_id → document_versions.id` (many-to-one)
- `nodes.parent_id → nodes.id` (self-referential tree)
- `selection_nodes` = join table, selection↔specific-version-node (pinning achieved naturally: node row IS version-specific)

**Indexes:** `nodes.logical_id` (fast cross-version match), `nodes.version_id`, `nodes.content_hash`

**JSON/Mongo store — generations:**

json

```json
{
  "generation_id": "uuid",
  "selection_id": 1,
  "node_snapshot": [{"node_id": 12, "logical_id": "4.2", "content_hash": "abc123"}],
  "prompt_used": "...",
  "raw_llm_response": "...",
  "parsed_test_cases": [{"title": "...", "steps": "...", "expected": "..."}],
  "status": "success | failed | retried",
  "created_at": "..."
}
```

Staleness computed at retrieval: for each `node_snapshot` entry, look up current node with same `logical_id` in latest version, compare `content_hash`. Mismatch → `is_stale: true` per node, aggregate flag on generation.

**No auth/RLS/roles** — explicitly out of scope.