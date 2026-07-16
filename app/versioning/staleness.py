from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import DocumentVersion, Node

StalenessStatus = Literal["changed", "unchanged", "removed"]


def compute_generation_staleness(
    db: Session,
    *,
    document_id: int,
    node_snapshot: list[dict[str, Any]],
) -> dict[str, Any]:
    latest_version_number = (
        db.query(func.max(DocumentVersion.version_number))
        .filter(DocumentVersion.document_id == document_id)
        .scalar()
    )
    if latest_version_number is None:
        return {
            "document_id": document_id,
            "latest_version": None,
            "is_stale": True,
            "nodes": [
                {
                    "node_id": item.get("node_id"),
                    "logical_id": item.get("logical_id"),
                    "status": "removed",
                    "old_content_hash": item.get("content_hash"),
                    "current_content_hash": None,
                    "current_node_id": None,
                }
                for item in node_snapshot
            ],
        }

    latest_version = (
        db.query(DocumentVersion)
        .filter(
            DocumentVersion.document_id == document_id,
            DocumentVersion.version_number == latest_version_number,
        )
        .one()
    )
    latest_nodes = {
        node.logical_id: node
        for node in db.query(Node).filter(Node.version_id == latest_version.id).all()
    }

    details: list[dict[str, Any]] = []
    is_stale = False
    for item in node_snapshot:
        logical_id = item["logical_id"]
        old_hash = item["content_hash"]
        latest_node = latest_nodes.get(logical_id)

        if latest_node is None:
            status: StalenessStatus = "removed"
            current_hash = None
            current_node_id = None
        elif latest_node.content_hash == old_hash:
            status = "unchanged"
            current_hash = latest_node.content_hash
            current_node_id = latest_node.id
        else:
            status = "changed"
            current_hash = latest_node.content_hash
            current_node_id = latest_node.id

        if status != "unchanged":
            is_stale = True

        details.append(
            {
                "node_id": item["node_id"],
                "logical_id": logical_id,
                "status": status,
                "old_content_hash": old_hash,
                "current_content_hash": current_hash,
                "current_node_id": current_node_id,
            }
        )

    return {
        "document_id": document_id,
        "latest_version": latest_version.version_number,
        "is_stale": is_stale,
        "nodes": details,
    }
