from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase


class OAuthRefreshToken(SemanticBase):
    __tablename__ = "oauth_refresh_tokens"
    __table_args__ = (
        Index("idx_ort_client", "client_id"),
        Index("idx_ort_principal", "principal_type", "principal_id"),
        Index("idx_ort_expires_at", "expires_at"),
        Index("idx_ort_revoked_at", "revoked_at"),
    )

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(128), nullable=False)
    principal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    principal_id: Mapped[str] = mapped_column(String(255), nullable=False)
    resource: Mapped[str] = mapped_column(String(512), nullable=False)
    scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    rotated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    replaced_by_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
