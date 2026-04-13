from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase


class SemanticConceptAlias(SemanticBase):
    __tablename__ = "semantic_concept_alias"
    __table_args__ = (
        UniqueConstraint("alias_key", "match_kind", name="uq_alias"),
        Index("idx_alias_concept", "concept_key"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    alias_key: Mapped[str] = mapped_column(String(200), nullable=False)
    concept_key: Mapped[str] = mapped_column(String(150), nullable=False)
    match_kind: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'exact'"))
    weight: Mapped[float] = mapped_column(DECIMAL(4, 3), nullable=False, server_default=text("1.000"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
