from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase


class WorkspaceColumnSemanticConceptMap(SemanticBase):
    __tablename__ = "workspace_column_semantic_concept_map"
    __table_args__ = (
        UniqueConstraint(
            "vertical_norm",
            "semantic_concept_id",
            "workspace_column_id",
            "relationship_kind",
            name="uq_ws_map",
        ),
        Index("idx_ws_map_concept", "vertical_norm", "semantic_concept_id"),
        Index("idx_ws_map_column", "workspace_column_id"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    vertical_norm: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'generic'"))
    semantic_concept_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("semantic_concept.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_column_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
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
