from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.ingest import get_db
from app.models import Node
from app.storage.generations import list_generation_records
from app.versioning.staleness import compute_generation_staleness

router = APIRouter(prefix="/generations", tags=["generations"])


def _document_id_for_generation(db: Session, record: dict[str, Any]) -> int:
    snapshot = record.get("node_snapshot") or []
    for item in snapshot:
        node = db.get(Node, item.get("node_id"))
        if node is not None:
            return node.version.document_id
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"Cannot compute staleness for generation {record.get('generation_id')}: "
            "none of its snapshot node IDs exist in the database."
        ),
    )


def _with_staleness(db: Session, record: dict[str, Any]) -> dict[str, Any]:
    document_id = _document_id_for_generation(db, record)
    return {
        **record,
        "staleness": compute_generation_staleness(
            db,
            document_id=document_id,
            node_snapshot=record.get("node_snapshot") or [],
        ),
    }


@router.get("")
def list_generations(
    selection_id: int | None = Query(default=None),
    node_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    records = list_generation_records()
    if selection_id is not None:
        records = [
            record
            for record in records
            if record.get("selection_id") == selection_id
        ]
    if node_id is not None:
        records = [
            record
            for record in records
            if any(
                item.get("node_id") == node_id
                for item in record.get("node_snapshot", [])
            )
        ]
    return [_with_staleness(db, record) for record in records]


@router.get("/{generation_id}")
def get_generation(
    generation_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    for record in list_generation_records():
        if record.get("generation_id") == generation_id:
            return _with_staleness(db, record)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Generation {generation_id} not found.",
    )
