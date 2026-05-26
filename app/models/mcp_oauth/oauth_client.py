from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, String, Text, text
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase


class OAuthClient(SemanticBase):
    __tablename__ = "oauth_clients"
    __table_args__ = (
        Index("idx_oauth_clients_expires_at", "expires_at"),
        Index("idx_oauth_clients_revoked_at", "revoked_at"),
    )

    client_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    client_secret_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    redirect_uris: Mapped[list] = mapped_column(JSON, nullable=False)
    grant_types: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    response_types: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_endpoint_auth_method: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    client_uri: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    logo_uri: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    contacts: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
