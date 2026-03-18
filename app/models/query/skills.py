from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase


class _QueryProperty:
    """Enables Model.query.filter_by(...) syntax using the shared DB session."""

    def __get__(self, obj, cls):
        from app.extensions import db as _db
        return _db.session.query(cls)


class QuerySkill(SemanticBase):
    __tablename__ = "query_skills"

    query = _QueryProperty()

    __table_args__ = (
        Index("idx_query_skills_workspace_active", "workspace_id", "is_active"),
        Index("idx_query_skills_skill_type", "skill_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    skill_type: Mapped[str] = mapped_column(String(64), nullable=False)
    query_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    config_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    is_shared: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_alert_state: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    alert_acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        server_default=None,
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )


class SkillSchedule(SemanticBase):
    __tablename__ = "skill_schedules"
    __table_args__ = (
        Index("idx_skill_schedules_skill_id", "skill_id"),
        Index("idx_skill_schedules_next_run", "next_run_at", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(36), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    cron_expr: Mapped[str] = mapped_column(String(128), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default=text("'UTC'"))
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    catch_up: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        nullable=True,
        server_default=None,
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )


class SkillExecution(SemanticBase):
    __tablename__ = "skill_executions"
    __table_args__ = (
        Index("idx_skill_executions_skill_id_status", "skill_id", "status"),
        Index("idx_skill_executions_job_id", "job_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    skill_id: Mapped[str] = mapped_column(String(36), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    schedule_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    job_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default=text("'queued'"))
    triggered_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
