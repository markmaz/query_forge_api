from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL, INTEGER, JSON, TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase


class SemanticUpdateCandidate(SemanticBase):
    __tablename__ = "semantic_update_candidate"
    __table_args__ = (
        UniqueConstraint("payload_hash", "source_scope", "workspace_scope_key", name="uidx_suc_hash_scope"),
        Index("idx_suc_governance_status", "governance_status"),
        Index("idx_suc_workspace_id", "workspace_id"),
        Index("idx_suc_concept_key", "concept_key"),
        Index("idx_suc_domain_key", "domain_key"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    failure_analysis_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("prompt_failure_analysis.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    concept_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    domain_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    change_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_count: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default=text("1"))
    confidence: Mapped[float] = mapped_column(DECIMAL(4, 3), nullable=False)
    governance_status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'pending'"))
    auto_apply_eligible: Mapped[bool] = mapped_column(TINYINT(1), nullable=False, server_default=text("0"))
    governance_reason_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_scope: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'global'"))
    workspace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    workspace_scope_key: Mapped[str] = mapped_column(String(80), nullable=False)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )
