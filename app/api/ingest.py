from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Document, DocumentVersion, Node
from app.parser import TreeNode, parse_markdown_file
from app.schemas import IngestResponse, ParserIrregularityRead

router = APIRouter(prefix="/documents", tags=["documents"])


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def _read_ingest_payload(request: Request) -> tuple[str, Path]:
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        payload: dict[str, Any] = await request.json()
        name = payload.get("name") or payload.get("document_name")
        file_path = payload.get("file_path") or payload.get("path")
    else:
        form = await request.form()
        name = form.get("name") or form.get("document_name")
        file_path = form.get("file_path") or form.get("path")

    if not isinstance(name, str) or not name.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Request must include a non-empty document name.",
        )

    if not isinstance(file_path, str) or not file_path.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Request must include file_path for Phase 4 ingest.",
        )

    path = Path(file_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path

    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Markdown file not found: {file_path}",
        )

    return name.strip(), path


def _persist_node_tree(
    db: Session,
    *,
    version: DocumentVersion,
    tree_node: TreeNode,
    parent: Node | None,
) -> int:
    node = Node(
        version=version,
        logical_id=tree_node.logical_id,
        heading=tree_node.heading,
        level=tree_node.level,
        path=tree_node.path,
        body=tree_node.body,
        parent=parent,
        content_hash=tree_node.content_hash,
        order_index=tree_node.order_index,
    )
    db.add(node)
    db.flush()

    count = 1
    for child in tree_node.children:
        count += _persist_node_tree(
            db,
            version=version,
            tree_node=child,
            parent=node,
        )
    return count


@router.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
async def ingest_document(request: Request, db: Session = Depends(get_db)) -> IngestResponse:
    name, source_path = await _read_ingest_payload(request)
    parsed_root, irregularities = parse_markdown_file(source_path)

    document = Document(name=name)
    db.add(document)
    db.flush()

    version = DocumentVersion(
        document=document,
        version_number=1,
        source_filename=source_path.name,
    )
    db.add(version)
    db.flush()

    node_count = _persist_node_tree(
        db,
        version=version,
        tree_node=parsed_root,
        parent=None,
    )
    db.commit()
    db.refresh(document)
    db.refresh(version)

    root_node = (
        db.query(Node)
        .filter(Node.version_id == version.id, Node.logical_id == parsed_root.logical_id)
        .one()
    )

    return IngestResponse(
        document=document,
        version=version,
        node_count=node_count,
        root_node_id=root_node.id,
        irregularities=[
            ParserIrregularityRead(
                kind=item.kind,
                description=item.description,
                handling=item.handling,
                location=item.location,
            )
            for item in irregularities
        ],
    )
