from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase


class OAuthAuthorizationCode(SemanticBase):
    __tablename__ = "oauth_authorization_codes"
    __table_args__ = (
        Index("idx_oac_client", "client_id"),
        Index("idx_oac_principal", "principal_type", "principal_id"),
        Index("idx_oac_expires_at", "expires_at"),
    )

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(128), nullable=False)
    principal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    principal_id: Mapped[str] = mapped_column(String(255), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    resource: Mapped[str] = mapped_column(String(512), nullable=False)
    scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    code_challenge: Mapped[str] = mapped_column(String(255), nullable=False)
    code_challenge_method: Mapped[str] = mapped_column(String(32), nullable=False)
    nonce: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    state_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
