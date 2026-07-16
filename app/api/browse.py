from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.ingest import get_db
from app.models import DocumentVersion, Node
from app.parser.tree_parser import ROOT_LOGICAL_ID
from app.schemas import NodeDetailRead, NodeSummaryRead, SearchResultRead, SectionRead

router = APIRouter(tags=["browse"])
ERROR_CODE_RE = re.compile(r"\bE\d+\b", re.IGNORECASE)


def _resolve_version(
    db: Session,
    *,
    document_id: int,
    version_number: int | None,
) -> DocumentVersion:
    if version_number is None:
        version_number = (
            db.query(func.max(DocumentVersion.version_number))
            .filter(DocumentVersion.document_id == document_id)
            .scalar()
        )
        if version_number is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Document {document_id} has no ingested versions.",
            )

    version = (
        db.query(DocumentVersion)
        .filter(
            DocumentVersion.document_id == document_id,
            DocumentVersion.version_number == version_number,
        )
        .one_or_none()
    )
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version_number} not found for document {document_id}.",
        )
    return version


def _node_summary(node: Node) -> NodeSummaryRead:
    return NodeSummaryRead(
        id=node.id,
        logical_id=node.logical_id,
        heading=node.heading,
        level=node.level,
        parent_id=node.parent_id,
        order_index=node.order_index,
    )


def _children_for(db: Session, node: Node) -> list[NodeSummaryRead]:
    children = (
        db.query(Node)
        .filter(Node.parent_id == node.id)
        .order_by(Node.order_index, Node.logical_id)
        .all()
    )
    return [_node_summary(child) for child in children]


def _snippet(node: Node, query: str, radius: int = 80) -> str:
    haystack = f"{node.heading}\n{node.body}"
    index = haystack.lower().find(query.lower())
    if index < 0:
        return node.body[: radius * 2].strip()

    start = max(index - radius, 0)
    end = min(index + len(query) + radius, len(haystack))
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(haystack) else ""
    return f"{prefix}{haystack[start:end].strip()}{suffix}"


def _related_error_codes(nodes: list[Node], query: str) -> set[str]:
    codes: set[str] = set()
    lowered = query.lower()
    for node in nodes:
        haystack = f"{node.heading}\n{node.body}"
        if lowered not in haystack.lower():
            continue
        for line in haystack.splitlines():
            if lowered in line.lower():
                codes.update(code.upper() for code in ERROR_CODE_RE.findall(line))
    return codes


@router.get("/documents/{document_id}/sections", response_model=list[SectionRead])
def list_sections(
    document_id: int,
    version_number: int | None = Query(default=None, alias="version"),
    db: Session = Depends(get_db),
) -> list[SectionRead]:
    version = _resolve_version(
        db,
        document_id=document_id,
        version_number=version_number,
    )
    root = (
        db.query(Node)
        .filter(Node.version_id == version.id, Node.logical_id == ROOT_LOGICAL_ID)
        .one_or_none()
    )
    if root is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Root node not found for document {document_id} version {version.version_number}.",
        )

    sections = (
        db.query(Node)
        .filter(
            Node.version_id == version.id,
            Node.parent_id == root.id,
            Node.level == 1,
        )
        .order_by(Node.order_index, Node.logical_id)
        .all()
    )

    return [
        SectionRead(
            **_node_summary(section).model_dump(),
            children=_children_for(db, section),
        )
        for section in sections
    ]


@router.get("/nodes/{node_id}", response_model=NodeDetailRead)
def get_node(node_id: int, db: Session = Depends(get_db)) -> NodeDetailRead:
    node = db.get(Node, node_id)
    if node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node {node_id} not found.",
        )

    return NodeDetailRead(
        id=node.id,
        version_id=node.version_id,
        logical_id=node.logical_id,
        heading=node.heading,
        level=node.level,
        path=node.path,
        body=node.body,
        parent_id=node.parent_id,
        content_hash=node.content_hash,
        order_index=node.order_index,
        children=_children_for(db, node),
    )


@router.get(
    "/documents/{document_id}/search",
    response_model=list[SearchResultRead],
)
def search_nodes(
    document_id: int,
    q: str = Query(min_length=1),
    version_number: int | None = Query(default=None, alias="version"),
    db: Session = Depends(get_db),
) -> list[SearchResultRead]:
    version = _resolve_version(
        db,
        document_id=document_id,
        version_number=version_number,
    )
    query = q.strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Search query cannot be blank.",
        )

    lowered = query.lower()
    nodes = (
        db.query(Node)
        .filter(Node.version_id == version.id)
        .order_by(Node.logical_id)
        .all()
    )
    related_codes = _related_error_codes(nodes, query)

    results: list[SearchResultRead] = []
    for node in nodes:
        haystack = f"{node.heading}\n{node.body}"
        direct_match = lowered in haystack.lower()
        code_reference_match = any(code.lower() in haystack.lower() for code in related_codes)
        if not direct_match and not code_reference_match:
            continue
        results.append(
            SearchResultRead(
                id=node.id,
                logical_id=node.logical_id,
                heading=node.heading,
                snippet=_snippet(node, query),
            )
        )
    return results
