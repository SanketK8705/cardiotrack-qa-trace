from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

GENERATION_STORE_PATH = Path(__file__).resolve().parents[2] / "data" / "generations.json"


def _read_records(path: Path = GENERATION_STORE_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"Generation store must contain a JSON list: {path}")
    return data


def append_generation_record(
    *,
    selection_id: int,
    node_snapshot: list[dict[str, Any]],
    prompt_used: str,
    raw_llm_response: str,
    parsed_test_cases: list[dict[str, Any]],
    status: str,
    errors: list[str] | None = None,
    path: Path = GENERATION_STORE_PATH,
) -> dict[str, Any]:
    records = _read_records(path)
    record = {
        "generation_id": str(uuid4()),
        "selection_id": selection_id,
        "node_snapshot": node_snapshot,
        "prompt_used": prompt_used,
        "raw_llm_response": raw_llm_response,
        "parsed_test_cases": parsed_test_cases,
        "status": status,
        "created_at": datetime.utcnow().isoformat(),
    }
    if errors:
        record["errors"] = errors

    records.append(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(records, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    tmp_path.replace(path)
    return record


def list_generation_records(path: Path = GENERATION_STORE_PATH) -> list[dict[str, Any]]:
    return _read_records(path)
