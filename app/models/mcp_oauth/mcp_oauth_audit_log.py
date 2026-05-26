from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, String, Text, text
from sqlalchemy.dialects.mysql import BIGINT, INTEGER, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase


class MCPOAuthAuditLog(SemanticBase):
    __tablename__ = "mcp_oauth_audit_log"
    __table_args__ = (
        Index("idx_mcp_audit_principal", "principal_type", "principal_id"),
        Index("idx_mcp_audit_workspace", "workspace_id"),
        Index("idx_mcp_audit_event", "event_type"),
        Index("idx_mcp_audit_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    principal_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    principal_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    requested_resource: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    requested_scopes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tool_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    domain_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    saved_query_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    denial_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    row_count_returned: Mapped[Optional[int]] = mapped_column(INTEGER(unsigned=True), nullable=True)
    rate_limit_bucket: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    trace_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    details_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
