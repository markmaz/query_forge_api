from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.mysql import BIGINT, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase


class DomainOverride(SemanticBase):
    __tablename__ = "domain_override"
    __table_args__ = (
        Index("idx_do_domain_key", "domain_key"),
        Index("idx_do_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    domain_key: Mapped[str] = mapped_column(String(255), nullable=False)
    override_type: Mapped[str] = mapped_column(String(64), nullable=False)
    override_key: Mapped[str] = mapped_column(String(255), nullable=False)
    override_value_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_candidate_id: Mapped[Optional[int]] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("semantic_update_candidate.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'active'"))
    approved_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )
