from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, String, Text, text
from sqlalchemy.dialects.mysql import BIGINT
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase


class OAuthConsent(SemanticBase):
    __tablename__ = "oauth_consents"
    __table_args__ = (
        Index("idx_oauth_consents_client_principal", "client_id", "principal_type", "principal_id"),
        Index("idx_oauth_consents_revoked_at", "revoked_at"),
    )

    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(128), nullable=False)
    principal_type: Mapped[str] = mapped_column(String(16), nullable=False)
    principal_id: Mapped[str] = mapped_column(String(255), nullable=False)
    resource: Mapped[str] = mapped_column(String(512), nullable=False)
    scope: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
