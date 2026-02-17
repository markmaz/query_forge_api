from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Computed, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, DECIMAL, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.semantic_registry import SemanticBase


class SemanticSuggestionRun(SemanticBase):
    __tablename__ = "semantic_suggestion_run"
    __table_args__ = (
        Index("idx_sem_suggestion_run_vertical", "vertical_norm"),
        Index("idx_sem_suggestion_run_status", "status"),
        Index("idx_sem_suggestion_run_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    vertical: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    vertical_norm: Mapped[str] = mapped_column(
        String(50),
        Computed("IFNULL(vertical, '__global__')", persisted=True),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'created'"))
    params_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    total_columns: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    processed_columns: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    valid_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    invalid_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    auto_approved_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    approved_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    rejected_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    applied_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    failed_apply_items: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )

    items: Mapped[list["SemanticSuggestionItem"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class SemanticSuggestionItem(SemanticBase):
    __tablename__ = "semantic_suggestion_item"
    __table_args__ = (
        UniqueConstraint("run_id", "model_column_id", name="uq_sem_suggestion_item_run_column"),
        Index("idx_sem_suggestion_item_run", "run_id"),
        Index("idx_sem_suggestion_item_status", "decision_status"),
        Index("idx_sem_suggestion_item_type", "proposed_semantic_type"),
        Index("idx_sem_suggestion_item_conf", "confidence"),
        Index("idx_item_concept", "proposed_concept_id"),
        Index("idx_item_concept_source", "proposed_concept_source"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("semantic_suggestion_run.id", ondelete="CASCADE"),
        nullable=False,
    )
    model_column_id: Mapped[int] = mapped_column(BIGINT(unsigned=True), nullable=False)
    model_table_id: Mapped[Optional[int]] = mapped_column(BIGINT(unsigned=True), nullable=True)
    table_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    column_name: Mapped[str] = mapped_column(String(255), nullable=False)
    data_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    samples_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    signals_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    llm_raw_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    proposed_concept_key: Mapped[Optional[str]] = mapped_column(String(150), nullable=True)
    proposed_concept_id: Mapped[Optional[int]] = mapped_column(BIGINT(unsigned=True), nullable=True)
    proposed_concept_source: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'llm'"))
    proposed_fallback_concept: Mapped[bool] = mapped_column(Integer, nullable=False, server_default=text("0"))
    proposed_concept_key_raw: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    proposed_semantic_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    proposed_sub_type: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    proposed_entity: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    proposed_granularity_rank: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    proposed_filter_allowed: Mapped[bool] = mapped_column(Integer, nullable=False, server_default=text("1"))
    proposed_group_by_allowed: Mapped[bool] = mapped_column(Integer, nullable=False, server_default=text("1"))
    proposed_aggregation_allowed: Mapped[bool] = mapped_column(Integer, nullable=False, server_default=text("1"))
    proposed_is_identifier: Mapped[bool] = mapped_column(Integer, nullable=False, server_default=text("0"))
    proposed_is_metric: Mapped[bool] = mapped_column(Integer, nullable=False, server_default=text("0"))
    proposed_display_priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    proposed_sensitive: Mapped[bool] = mapped_column(Integer, nullable=False, server_default=text("0"))
    confidence: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(5, 4), nullable=True)
    reasons_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    warnings_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    validation_errors_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    is_valid: Mapped[bool] = mapped_column(Integer, nullable=False, server_default=text("0"))
    decision_status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'pending'"))
    decision_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )

    run: Mapped[SemanticSuggestionRun] = relationship(back_populates="items")
