from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, text
from sqlalchemy.dialects.mysql import INTEGER, TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase


class WorkspaceMCPSettings(SemanticBase):
    __tablename__ = "workspace_mcp_settings"

    workspace_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    enabled: Mapped[bool] = mapped_column(TINYINT(1), nullable=False, server_default=text("0"))
    enabled_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    enabled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    disabled_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    disabled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    default_preview_row_limit: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default=text("100"))
    max_preview_row_limit: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default=text("500"))
    block_sensitive_domains: Mapped[bool] = mapped_column(TINYINT(1), nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )
