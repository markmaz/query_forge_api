from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase


class PromptFeedback(SemanticBase):
    __tablename__ = "prompt_feedback"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", "trace_id", name="uq_pf_workspace_user_trace"),
        Index("idx_pf_workspace_user_created", "workspace_id", "user_id", "created_at"),
        Index("idx_pf_trace", "trace_id"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    vote: Mapped[str] = mapped_column(Enum("up", "down", name="prompt_feedback_vote"), nullable=False)
    normalized_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prompt_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    meta_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )
