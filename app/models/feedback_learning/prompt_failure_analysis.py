from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase


class PromptFailureAnalysis(SemanticBase):
    __tablename__ = "prompt_failure_analysis"
    __table_args__ = (
        UniqueConstraint("prompt_feedback_id", name="uidx_pfa_prompt_feedback_id"),
        Index("idx_pfa_status", "status"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    prompt_feedback_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("prompt_feedback.id", ondelete="CASCADE"),
        nullable=False,
    )
    evaluator_model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    evaluator_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'pending'"))
    failure_verdict: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(DECIMAL(4, 3), nullable=True)
    analysis_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    raw_llm_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )
