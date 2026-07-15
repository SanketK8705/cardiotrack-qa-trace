from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    versions = relationship(
        "DocumentVersion",
        back_populates="document",
        cascade="all, delete-orphan",
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    version_number = Column(Integer, nullable=False)
    ingested_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    source_filename = Column(Text, nullable=False)

    document = relationship("Document", back_populates="versions")
    nodes = relationship(
        "Node",
        back_populates="version",
        cascade="all, delete-orphan",
    )


class Node(Base):
    __tablename__ = "nodes"

    id = Column(Integer, primary_key=True, index=True)
    version_id = Column(Integer, ForeignKey("document_versions.id"), nullable=False)
    logical_id = Column(Text, nullable=False)
    heading = Column(Text, nullable=False)
    level = Column(Integer, nullable=False)
    path = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    parent_id = Column(Integer, ForeignKey("nodes.id"), nullable=True)
    content_hash = Column(String(64), nullable=False)
    order_index = Column(Integer, nullable=False)

    version = relationship("DocumentVersion", back_populates="nodes")
    parent = relationship("Node", remote_side=[id], back_populates="children")
    children = relationship("Node", back_populates="parent")
    selection_links = relationship(
        "SelectionNode",
        back_populates="node",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_nodes_logical_id", "logical_id"),
        Index("ix_nodes_version_id", "version_id"),
        Index("ix_nodes_content_hash", "content_hash"),
    )


class Selection(Base):
    __tablename__ = "selections"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    nodes = relationship(
        "SelectionNode",
        back_populates="selection",
        cascade="all, delete-orphan",
    )


class SelectionNode(Base):
    __tablename__ = "selection_nodes"

    id = Column(Integer, primary_key=True, index=True)
    selection_id = Column(Integer, ForeignKey("selections.id"), nullable=False)
    node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False)

    selection = relationship("Selection", back_populates="nodes")
    node = relationship("Node", back_populates="selection_links")


__all__ = [
    "Document",
    "DocumentVersion",
    "Node",
    "Selection",
    "SelectionNode",
]
