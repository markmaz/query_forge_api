from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase


class ModelColumnSemantic(SemanticBase):
    """Partial ORM model for semantic assignment columns on model_column."""

    __tablename__ = "model_column"
    __table_args__ = (
        Index("idx_model_column_semantic_concept_id", "semantic_concept_id"),
        Index("idx_model_column_semantic_concept_key", "semantic_concept_key"),
        Index("idx_model_column_table_semantic_key", "model_table_id", "semantic_concept_key"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    model_table_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    column_name: Mapped[str] = mapped_column(String(200), nullable=False)

    semantic_concept_id: Mapped[Optional[int]] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("semantic_concept.id", ondelete="SET NULL"),
        nullable=True,
    )
    semantic_concept_key: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    semantic_entity: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    semantic_sub_type: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    semantic_granularity_rank: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    semantic_source: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    semantic_confidence: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(4, 3), nullable=True)
    semantic_reasons_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    semantic_warnings_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    semantic_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ModelColumnSemanticConceptMap(SemanticBase):
    __tablename__ = "model_column_semantic_concept_map"
    __table_args__ = (
        UniqueConstraint(
            "vertical_norm",
            "semantic_concept_id",
            "model_column_id",
            "relationship_kind",
            name="uq_map",
        ),
        Index("idx_map_concept", "vertical_norm", "semantic_concept_id"),
        Index("idx_map_column", "model_column_id"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    vertical_norm: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'generic'"))
    semantic_concept_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("semantic_concept.id", ondelete="CASCADE"),
        nullable=False,
    )
    model_column_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("model_column.id", ondelete="CASCADE"),
        nullable=False,
    )
    relationship_kind: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'primary'"))
    weight: Mapped[Decimal] = mapped_column(DECIMAL(4, 3), nullable=False, server_default=text("1.000"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class SemanticValueAlias(SemanticBase):
    __tablename__ = "semantic_value_alias"
    __table_args__ = (
        UniqueConstraint("vertical_norm", "semantic_concept_id", "alias_value", "match_kind", name="uq_val_alias"),
        Index("idx_val_alias_concept", "vertical_norm", "semantic_concept_id"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    vertical_norm: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'generic'"))
    semantic_concept_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("semantic_concept.id", ondelete="CASCADE"),
        nullable=False,
    )
    canonical_value: Mapped[str] = mapped_column(String(300), nullable=False)
    alias_value: Mapped[str] = mapped_column(String(300), nullable=False)
    match_kind: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'contains'"))
    weight: Mapped[Decimal] = mapped_column(DECIMAL(4, 3), nullable=False, server_default=text("1.000"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
