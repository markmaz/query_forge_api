from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic_registry import SemanticBase


class ForgeMatchSession(SemanticBase):
    __tablename__ = "forge_match_session"
    __table_args__ = (
        Index("idx_forge_match_session_workspace_created", "workspace_id", "created_at"),
        Index("idx_forge_match_session_status", "status"),
        Index("idx_forge_match_session_analysis_job", "analysis_job_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    uploaded_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'uploaded'"))
    sheet_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    source_record_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    analysis_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    analysis_completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    analysis_job_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    current_phase: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    current_source_row_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    analyzed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    cancel_requested: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    analysis_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    summary_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        server_default=None,
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )


class ForgeMatchSourceRecord(SemanticBase):
    __tablename__ = "forge_match_source_record"
    __table_args__ = (
        Index("idx_forge_match_source_session_name", "session_id", "source_field_name"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("forge_match_session.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    row_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sheet_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    row_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_field_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_object_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sample_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    normalized_search_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_row_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class ForgeMatchResult(SemanticBase):
    __tablename__ = "forge_match_result"
    __table_args__ = (
        Index("idx_forge_match_result_session_status", "session_id", "status"),
        Index("idx_forge_match_result_best_column", "best_match_workspace_column_id"),
        Index("idx_forge_match_result_manual_column", "manually_selected_workspace_column_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("forge_match_session.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    source_record_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("forge_match_source_record.id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    best_match_workspace_column_id: Mapped[Optional[int]] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("workspace_column.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    alternate_workspace_column_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    retrieved_candidates_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    llm_response_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    match_decision: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'no_confident_match'"))
    reason_codes_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ambiguity_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    llm_confidence: Mapped[Optional[float]] = mapped_column(DECIMAL(5, 4), nullable=True)
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    confidence_band: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'low'"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'suggested'"))
    review_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    manually_selected_workspace_column_id: Mapped[Optional[int]] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("workspace_column.id", ondelete="SET NULL", onupdate="CASCADE"),
        nullable=True,
    )
    reviewer_user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        server_default=None,
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )
