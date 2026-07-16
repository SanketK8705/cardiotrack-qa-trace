from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi import Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Document, DocumentVersion, Node
from app.parser import TreeNode, parse_markdown_file
from app.schemas import (
    IngestResponse,
    NodeChangeRead,
    NodeDiffResponse,
    ParserIrregularityRead,
    VersionChangeSummary,
)

router = APIRouter(prefix="/documents", tags=["documents"])


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def _read_ingest_payload(
    request: Request,
    *,
    require_name: bool,
) -> tuple[str | None, Path]:
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        payload: dict[str, Any] = await request.json()
        name = payload.get("name") or payload.get("document_name")
        file_path = payload.get("file_path") or payload.get("path")
    else:
        form = await request.form()
        name = form.get("name") or form.get("document_name")
        file_path = form.get("file_path") or form.get("path")

    if require_name and (not isinstance(name, str) or not name.strip()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Request must include a non-empty document name.",
        )

    if not isinstance(file_path, str) or not file_path.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Request must include file_path for markdown ingest.",
        )

    path = Path(file_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path

    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Markdown file not found: {file_path}",
        )

    return name.strip() if isinstance(name, str) and name.strip() else None, path


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


def _version_by_number(
    db: Session,
    *,
    document_id: int,
    version_number: int,
) -> DocumentVersion:
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


def _nodes_by_logical_id(db: Session, version_id: int) -> dict[str, Node]:
    return {
        node.logical_id: node
        for node in db.query(Node).filter(Node.version_id == version_id).all()
    }


def _build_change_summary(
    db: Session,
    *,
    previous_version: DocumentVersion,
    current_version: DocumentVersion,
) -> VersionChangeSummary:
    previous_nodes = _nodes_by_logical_id(db, previous_version.id)
    current_nodes = _nodes_by_logical_id(db, current_version.id)

    changed: list[NodeChangeRead] = []
    inserted: list[NodeChangeRead] = []
    removed: list[NodeChangeRead] = []

    # Numbered headings make the path-like logical_id stable across body edits and
    # insertions such as 5.3. This deliberately avoids title matching, because
    # duplicate titles like "Error Codes" exist. The tradeoff: a renumbered section
    # with unchanged text, or a deleted section whose number is later reused by an
    # unrelated section, will be treated as a different or matching logical node.
    for logical_id, current_node in sorted(current_nodes.items()):
        previous_node = previous_nodes.get(logical_id)
        if previous_node is None:
            inserted.append(
                NodeChangeRead(
                    logical_id=logical_id,
                    status="inserted",
                    current_node_id=current_node.id,
                )
            )
        elif previous_node.content_hash != current_node.content_hash:
            changed.append(
                NodeChangeRead(
                    logical_id=logical_id,
                    status="changed",
                    previous_node_id=previous_node.id,
                    current_node_id=current_node.id,
                )
            )

    for logical_id, previous_node in sorted(previous_nodes.items()):
        if logical_id not in current_nodes:
            removed.append(
                NodeChangeRead(
                    logical_id=logical_id,
                    status="removed",
                    previous_node_id=previous_node.id,
                )
            )

    return VersionChangeSummary(
        from_version=previous_version.version_number,
        to_version=current_version.version_number,
        changed=changed,
        inserted=inserted,
        removed=removed,
    )


def _diff_nodes(
    *,
    document_id: int,
    logical_id: str,
    from_version: DocumentVersion,
    to_version: DocumentVersion,
    old_node: Node | None,
    new_node: Node | None,
) -> NodeDiffResponse:
    if old_node is None and new_node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Node {logical_id!r} does not exist in versions "
                f"{from_version.version_number} or {to_version.version_number}."
            ),
        )

    if old_node is None:
        status_value = "inserted"
        changed = True
    elif new_node is None:
        status_value = "removed"
        changed = True
    elif old_node.content_hash != new_node.content_hash:
        status_value = "changed"
        changed = True
    else:
        status_value = "unchanged"
        changed = False

    return NodeDiffResponse(
        document_id=document_id,
        logical_id=logical_id,
        from_version=from_version.version_number,
        to_version=to_version.version_number,
        status=status_value,
        changed=changed,
        old_node_id=old_node.id if old_node else None,
        new_node_id=new_node.id if new_node else None,
        old_body=old_node.body if old_node else None,
        new_body=new_node.body if new_node else None,
    )


def _ingest_new_version(
    db: Session,
    *,
    document: Document,
    source_path: Path,
    version_number: int,
) -> tuple[DocumentVersion, int, int, list[ParserIrregularityRead]]:
    parsed_root, irregularities = parse_markdown_file(source_path)

    version = DocumentVersion(
        document=document,
        version_number=version_number,
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
    db.flush()

    root_node = (
        db.query(Node)
        .filter(Node.version_id == version.id, Node.logical_id == parsed_root.logical_id)
        .one()
    )

    return (
        version,
        node_count,
        root_node.id,
        [
            ParserIrregularityRead(
                kind=item.kind,
                description=item.description,
                handling=item.handling,
                location=item.location,
            )
            for item in irregularities
        ],
    )


@router.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
async def ingest_document(request: Request, db: Session = Depends(get_db)) -> IngestResponse:
    name, source_path = await _read_ingest_payload(request, require_name=True)

    document = Document(name=name)
    db.add(document)
    db.flush()

    version, node_count, root_node_id, irregularities = _ingest_new_version(
        db,
        document=document,
        source_path=source_path,
        version_number=1,
    )
    db.commit()
    db.refresh(document)
    db.refresh(version)

    return IngestResponse(
        document=document,
        version=version,
        node_count=node_count,
        root_node_id=root_node_id,
        irregularities=irregularities,
    )


@router.post(
    "/{document_id}/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_document_version(
    document_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> IngestResponse:
    _, source_path = await _read_ingest_payload(request, require_name=False)

    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found.",
        )

    previous_number = (
        db.query(func.max(DocumentVersion.version_number))
        .filter(DocumentVersion.document_id == document_id)
        .scalar()
    )
    if previous_number is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document {document_id} has no existing version to extend.",
        )

    previous_version = _version_by_number(
        db,
        document_id=document_id,
        version_number=previous_number,
    )
    version, node_count, root_node_id, irregularities = _ingest_new_version(
        db,
        document=document,
        source_path=source_path,
        version_number=previous_number + 1,
    )
    changes = _build_change_summary(
        db,
        previous_version=previous_version,
        current_version=version,
    )

    db.commit()
    db.refresh(document)
    db.refresh(version)

    return IngestResponse(
        document=document,
        version=version,
        node_count=node_count,
        root_node_id=root_node_id,
        irregularities=irregularities,
        changes=changes,
    )


@router.get(
    "/{document_id}/nodes/{logical_id}/diff",
    response_model=NodeDiffResponse,
)
def diff_node(
    document_id: int,
    logical_id: str,
    from_version_number: int = Query(alias="from"),
    to_version_number: int = Query(alias="to"),
    db: Session = Depends(get_db),
) -> NodeDiffResponse:
    from_version = _version_by_number(
        db,
        document_id=document_id,
        version_number=from_version_number,
    )
    to_version = _version_by_number(
        db,
        document_id=document_id,
        version_number=to_version_number,
    )

    old_node = (
        db.query(Node)
        .filter(Node.version_id == from_version.id, Node.logical_id == logical_id)
        .one_or_none()
    )
    new_node = (
        db.query(Node)
        .filter(Node.version_id == to_version.id, Node.logical_id == logical_id)
        .one_or_none()
    )

    return _diff_nodes(
        document_id=document_id,
        logical_id=logical_id,
        from_version=from_version,
        to_version=to_version,
        old_node=old_node,
        new_node=new_node,
    )
