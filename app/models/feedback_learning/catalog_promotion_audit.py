from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, String, Text, text
from sqlalchemy.dialects.mysql import BIGINT, INTEGER
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase


class CatalogPromotionAudit(SemanticBase):
    __tablename__ = "catalog_promotion_audit"
    __table_args__ = (
        Index("idx_cpa_source", "source_type", "source_id"),
        Index("idx_cpa_status", "promotion_status"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    target_table: Mapped[str] = mapped_column(String(128), nullable=False)
    target_record_key: Mapped[str] = mapped_column(String(255), nullable=False)
    promotion_action: Mapped[str] = mapped_column(String(64), nullable=False)
    promotion_status: Mapped[str] = mapped_column(String(32), nullable=False)
    promoted_by: Mapped[str] = mapped_column(String(255), nullable=False)
    promoted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    retry_count: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default=text("0"))
    last_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
