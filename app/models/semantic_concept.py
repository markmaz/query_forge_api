from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic_registry import SemanticBase


class SemanticConcept(SemanticBase):
    __tablename__ = "semantic_concept"
    __table_args__ = (
        UniqueConstraint("vertical_norm", "concept_key", name="uq_concept_vertical_key"),
        Index("idx_concept_vertical_type", "vertical_norm", "semantic_type"),
        Index("idx_concept_key", "concept_key"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    vertical_norm: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'generic'"))
    concept_key: Mapped[str] = mapped_column(String(150), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    semantic_type: Mapped[str] = mapped_column(String(50), nullable=False)
    sub_type: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    entity: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    granularity_rank: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    filter_allowed: Mapped[bool] = mapped_column(Integer, nullable=False, server_default=text("1"))
    group_by_allowed: Mapped[bool] = mapped_column(Integer, nullable=False, server_default=text("1"))
    aggregation_allowed: Mapped[bool] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_identifier: Mapped[bool] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_metric: Mapped[bool] = mapped_column(Integer, nullable=False, server_default=text("0"))
    display_priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    sensitive: Mapped[bool] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )
