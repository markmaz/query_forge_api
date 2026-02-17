from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Computed, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class SemanticBase(DeclarativeBase):
    """Declarative base for semantic registry ORM models."""


class SemanticRegistry(SemanticBase):
    """Global or vertical-scoped business concept metadata."""

    __tablename__ = "semantic_registry"
    __table_args__ = (
        UniqueConstraint("vertical_norm", "concept_key", name="uq_semantic_registry_vertical_concept"),
        Index("idx_semantic_registry_vertical_type", "vertical_norm", "semantic_type"),
        Index("idx_semantic_registry_vertical_entity", "vertical_norm", "entity"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    vertical: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    vertical_norm: Mapped[str] = mapped_column(
        String(50),
        Computed("IFNULL(vertical, '__global__')", persisted=True),
        nullable=False,
    )
    concept_key: Mapped[str] = mapped_column(String(150), nullable=False)
    semantic_type: Mapped[str] = mapped_column(String(50), nullable=False)
    sub_type: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    entity: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    granularity_rank: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    filter_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    group_by_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    aggregation_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    is_identifier: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    is_metric: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    display_priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )

    column_maps: Mapped[list["SemanticColumnMap"]] = relationship(
        back_populates="semantic_registry",
        cascade="all, delete-orphan",
    )
    parent_relationships: Mapped[list["SemanticRelationship"]] = relationship(
        foreign_keys="SemanticRelationship.parent_concept_id",
        back_populates="parent_concept",
        cascade="all, delete-orphan",
    )
    child_relationships: Mapped[list["SemanticRelationship"]] = relationship(
        foreign_keys="SemanticRelationship.child_concept_id",
        back_populates="child_concept",
        cascade="all, delete-orphan",
    )


class SemanticColumnMap(SemanticBase):
    """Mapping between semantic concepts and workspace/model columns."""

    __tablename__ = "semantic_column_map"
    __table_args__ = (
        UniqueConstraint(
            "semantic_registry_id",
            "workspace_norm",
            "model_column_id",
            name="uq_map_semreg_workspace_modelcol",
        ),
        UniqueConstraint(
            "semantic_registry_id",
            "workspace_norm",
            "table_name",
            "column_name",
            name="uq_map_semreg_workspace_tablecol",
        ),
        Index("idx_map_workspace_modelcol", "workspace_norm", "model_column_id"),
        Index("idx_map_workspace_tablecol", "workspace_norm", "table_name", "column_name"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    semantic_registry_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("semantic_registry.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    workspace_norm: Mapped[str] = mapped_column(
        String(100),
        Computed("IFNULL(workspace_id, '__global__')", persisted=True),
        nullable=False,
    )
    model_column_id: Mapped[Optional[int]] = mapped_column(BIGINT(unsigned=True), nullable=True)
    table_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    column_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    priority_rank: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    confidence_score: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(4, 3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    semantic_registry: Mapped[SemanticRegistry] = relationship(back_populates="column_maps")


class SemanticRelationship(SemanticBase):
    """Directed semantic concept relationship graph edges."""

    __tablename__ = "semantic_relationship"
    __table_args__ = (
        UniqueConstraint("parent_concept_id", "child_concept_id", "relationship_type", name="uq_rel"),
        Index("idx_rel_parent", "parent_concept_id"),
        Index("idx_rel_child", "child_concept_id"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    parent_concept_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("semantic_registry.id", ondelete="CASCADE"),
        nullable=False,
    )
    child_concept_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("semantic_registry.id", ondelete="CASCADE"),
        nullable=False,
    )
    relationship_type: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))

    parent_concept: Mapped[SemanticRegistry] = relationship(
        foreign_keys=[parent_concept_id],
        back_populates="parent_relationships",
    )
    child_concept: Mapped[SemanticRegistry] = relationship(
        foreign_keys=[child_concept_id],
        back_populates="child_relationships",
    )
