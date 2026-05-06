from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.mysql import BIGINT, INTEGER, JSON, TINYINT
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase


class MCPPrincipalGrant(SemanticBase):
    __tablename__ = "mcp_principal_grants"
    __table_args__ = (
        UniqueConstraint("principal_type", "principal_id", "workspace_id", name="uidx_mpg_principal_workspace"),
        Index("idx_mpg_principal_workspace", "principal_type", "principal_id", "workspace_id"),
        Index("idx_mpg_workspace", "workspace_id", "enabled"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    principal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    principal_id: Mapped[str] = mapped_column(String(255), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(TINYINT(1), nullable=False, server_default=text("1"))
    allowed_tools: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    allowed_domain_keys: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    can_preview: Mapped[bool] = mapped_column(TINYINT(1), nullable=False, server_default=text("0"))
    preview_row_limit: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default=text("100"))
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        server_onupdate=text("CURRENT_TIMESTAMP"),
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
