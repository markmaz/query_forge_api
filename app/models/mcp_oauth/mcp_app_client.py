from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase


class MCPAppClient(SemanticBase):
    __tablename__ = "mcp_app_clients"
    __table_args__ = (
        Index("idx_mac_workspace", "owning_workspace_id"),
        Index("idx_mac_revoked_at", "revoked_at"),
    )

    client_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    client_secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owning_workspace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_user_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rotation_required_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
