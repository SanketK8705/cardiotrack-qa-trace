from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.ingest import get_db
from app.models import Node, Selection, SelectionNode
from app.schemas import (
    SelectionCreate,
    SelectionDetailRead,
    SelectionPinnedNodeRead,
)

router = APIRouter(prefix="/selections", tags=["selections"])


def _selection_response(selection: Selection) -> SelectionDetailRead:
    pinned_nodes = [
        SelectionPinnedNodeRead(
            id=link.node.id,
            logical_id=link.node.logical_id,
            heading=link.node.heading,
            version_id=link.node.version_id,
            body=link.node.body,
        )
        for link in selection.nodes
    ]
    return SelectionDetailRead(
        id=selection.id,
        name=selection.name,
        created_at=selection.created_at,
        nodes=pinned_nodes,
    )


@router.post("", response_model=SelectionDetailRead, status_code=status.HTTP_201_CREATED)
def create_selection(
    payload: SelectionCreate,
    db: Session = Depends(get_db),
) -> SelectionDetailRead:
    name = payload.name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Selection name cannot be blank.",
        )

    unique_node_ids = list(dict.fromkeys(payload.node_ids))
    if not unique_node_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Selection must include at least one node_id.",
        )

    nodes = db.query(Node).filter(Node.id.in_(unique_node_ids)).all()
    nodes_by_id = {node.id: node for node in nodes}
    missing_ids = [node_id for node_id in unique_node_ids if node_id not in nodes_by_id]
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node id(s) not found: {', '.join(str(node_id) for node_id in missing_ids)}",
        )

    selection = Selection(name=name)
    db.add(selection)
    db.flush()

    # Selection pinning falls out of the data model: each SelectionNode stores a
    # concrete node_id, and node rows are version-specific through Node.version_id.
    # Later document ingests create new Node rows, so existing selections keep
    # pointing at the original version snapshot without extra pinning machinery.
    for node_id in unique_node_ids:
        db.add(SelectionNode(selection=selection, node=nodes_by_id[node_id]))

    db.commit()
    db.refresh(selection)
    return _selection_response(selection)


@router.get("/{selection_id}", response_model=SelectionDetailRead)
def get_selection(
    selection_id: int,
    db: Session = Depends(get_db),
) -> SelectionDetailRead:
    selection = db.get(Selection, selection_id)
    if selection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Selection {selection_id} not found.",
        )
    return _selection_response(selection)
