from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic_registry import SemanticBase




class ForgeInsightsProject(SemanticBase):
    __tablename__ = "forge_insights_project"
    __table_args__ = (
        Index("idx_fip_workspace_user_updated", "workspace_id", "user_id", "updated_at"),
        Index("idx_fip_workspace_user_archived", "workspace_id", "user_id", "is_archived"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )


class ForgeInsightsThread(SemanticBase):
    __tablename__ = "forge_insights_thread"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", "conversation_id", name="uq_fit_workspace_user_conversation"),
        Index("idx_fit_workspace_user_last", "workspace_id", "user_id", "last_message_at"),
        Index("idx_fit_workspace_user_updated", "workspace_id", "user_id", "updated_at"),
        Index("idx_fit_project_updated", "project_id", "updated_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    project_id: Mapped[Optional[int]] = mapped_column(
        BIGINT(unsigned=True),
        ForeignKey("forge_insights_project.id", ondelete="SET NULL"),
        nullable=True,
    )
    conversation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    preview_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("0"))
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )
