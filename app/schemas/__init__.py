from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


class NodeSummaryRead(BaseModel):
    id: int
    logical_id: str
    heading: str
    level: int
    parent_id: int | None
    order_index: int


class SectionRead(NodeSummaryRead):
    children: list[NodeSummaryRead] = Field(default_factory=list)


class NodeDetailRead(NodeRead):
    children: list[NodeSummaryRead] = Field(default_factory=list)


class SearchResultRead(BaseModel):
    id: int
    logical_id: str
    heading: str
    snippet: str


class SelectionCreate(BaseModel):
    name: str
    node_ids: list[int] = Field(default_factory=list)


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


class SelectionPinnedNodeRead(BaseModel):
    id: int
    logical_id: str
    heading: str
    version_id: int
    body: str


class SelectionDetailRead(BaseModel):
    id: int
    name: str
    created_at: datetime
    nodes: list[SelectionPinnedNodeRead] = Field(default_factory=list)


class ParserIrregularityRead(BaseModel):
    kind: str
    description: str
    handling: str
    location: str | None = None


class NodeChangeRead(BaseModel):
    logical_id: str
    status: str
    previous_node_id: int | None = None
    current_node_id: int | None = None


class VersionChangeSummary(BaseModel):
    from_version: int | None = None
    to_version: int
    changed: list[NodeChangeRead] = Field(default_factory=list)
    inserted: list[NodeChangeRead] = Field(default_factory=list)
    removed: list[NodeChangeRead] = Field(default_factory=list)


class IngestResponse(BaseModel):
    document: DocumentRead
    version: DocumentVersionRead
    node_count: int
    root_node_id: int
    irregularities: list[ParserIrregularityRead]
    changes: VersionChangeSummary | None = None


class NodeDiffResponse(BaseModel):
    document_id: int
    logical_id: str
    from_version: int
    to_version: int
    status: str
    changed: bool
    old_node_id: int | None = None
    new_node_id: int | None = None
    old_body: str | None = None
    new_body: str | None = None


class GenerationRecordRead(BaseModel):
    generation_id: str
    selection_id: int
    node_snapshot: list[dict[str, Any]]
    prompt_used: str
    raw_llm_response: str
    parsed_test_cases: list[dict[str, Any]]
    status: str
    created_at: str
    errors: list[str] | None = None


__all__ = [
    "DocumentCreate",
    "DocumentRead",
    "DocumentVersionRead",
    "GenerationRecordRead",
    "IngestResponse",
    "NodeChangeRead",
    "NodeDiffResponse",
    "NodeDetailRead",
    "NodeRead",
    "NodeSummaryRead",
    "ParserIrregularityRead",
    "SearchResultRead",
    "SelectionCreate",
    "SelectionDetailRead",
    "SelectionNodeRead",
    "SelectionPinnedNodeRead",
    "SelectionRead",
    "SectionRead",
    "VersionChangeSummary",
]
