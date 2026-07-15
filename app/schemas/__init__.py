from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentCreate(BaseModel):
    name: str
    file_path: str | None = None


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime


class DocumentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    version_number: int
    ingested_at: datetime
    source_filename: str


class NodeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version_id: int
    logical_id: str
    heading: str
    level: int
    path: str
    body: str
    parent_id: int | None
    content_hash: str
    order_index: int


class SelectionCreate(BaseModel):
    name: str
    node_ids: list[int] = []


class SelectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime


class SelectionNodeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    selection_id: int
    node_id: int


class ParserIrregularityRead(BaseModel):
    kind: str
    description: str
    handling: str
    location: str | None = None


class IngestResponse(BaseModel):
    document: DocumentRead
    version: DocumentVersionRead
    node_count: int
    root_node_id: int
    irregularities: list[ParserIrregularityRead]


__all__ = [
    "DocumentCreate",
    "DocumentRead",
    "DocumentVersionRead",
    "IngestResponse",
    "NodeRead",
    "ParserIrregularityRead",
    "SelectionCreate",
    "SelectionNodeRead",
    "SelectionRead",
]
