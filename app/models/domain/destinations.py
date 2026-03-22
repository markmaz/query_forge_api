"""
app/models/destinations.py

WorkspaceDestination model — workspace-level notification destination registry.

Destinations are configured once by admins and referenced by destination_id
in skill configs. Sensitive config (webhook URLs, tokens) is encrypted at rest
using Fernet symmetric encryption.

Fernet key must be set in config as DESTINATION_ENCRYPTION_KEY.
Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Boolean, DateTime, Enum, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

logger = logging.getLogger(__name__)

DESTINATION_TYPES = ("slack", "teams", "webhook", "email_group")
TEST_STATUSES = ("success", "failed")

# ---------------------------------------------------------------------------
# Config shapes per destination type (for validation and UI rendering)
# ---------------------------------------------------------------------------

DESTINATION_CONFIG_SCHEMAS: dict[str, dict] = {
    "slack": {
        "required": ["webhook_url"],
        "sensitive": ["webhook_url"],
        "properties": {
            "webhook_url": {"type": "string", "title": "Webhook URL", "ui:widget": "password"},
        },
    },
    "teams": {
        "required": ["webhook_url"],
        "sensitive": ["webhook_url"],
        "properties": {
            "webhook_url": {"type": "string", "title": "Webhook URL", "ui:widget": "password"},
        },
    },
    "webhook": {
        "required": ["url"],
        "sensitive": ["url", "auth_token"],
        "properties": {
            "url": {"type": "string", "title": "URL", "ui:widget": "password"},
            "method": {"type": "string", "title": "Method", "enum": ["POST", "PUT"], "default": "POST"},
            "auth_token": {"type": "string", "title": "Auth token (Bearer)", "ui:widget": "password"},
            "headers": {"type": "object", "title": "Custom headers", "ui:widget": "key-value"},
        },
    },
    "email_group": {
        "required": ["recipients"],
        "sensitive": [],
        "properties": {
            "recipients": {"type": "array", "title": "Recipients", "items": {"type": "string", "format": "email"}, "ui:widget": "email-list"},
            "reply_to": {"type": "string", "title": "Reply-to", "format": "email", "ui:widget": "text"},
            "from_name": {"type": "string", "title": "From name", "default": "QueryForge", "ui:widget": "text"},
        },
    },
}


# ---------------------------------------------------------------------------
# Fernet helpers
# ---------------------------------------------------------------------------


def _get_fernet() -> Fernet:
    from flask import current_app
    key = current_app.config.get("DESTINATION_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError(
            "DESTINATION_ENCRYPTION_KEY is not set. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_config(config: dict) -> str:
    """Encrypt a config dict to a Fernet token string."""
    plaintext = json.dumps(config, ensure_ascii=False).encode("utf-8")
    return _get_fernet().encrypt(plaintext).decode("utf-8")


def decrypt_config(encrypted: str) -> dict:
    """Decrypt a Fernet token string back to a config dict."""
    try:
        plaintext = _get_fernet().decrypt(encrypted.encode("utf-8"))
        return json.loads(plaintext.decode("utf-8"))
    except InvalidToken:
        raise ValueError("Could not decrypt destination config — key may have changed.")


def mask_config(config: dict, destination_type: str) -> dict:
    """Return config with sensitive fields replaced by '••••••'."""
    sensitive = DESTINATION_CONFIG_SCHEMAS.get(destination_type, {}).get("sensitive", [])
    return {
        k: "••••••" if k in sensitive and v else v
        for k, v in config.items()
    }


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class WorkspaceDestination(db.Model):
    __tablename__ = "workspace_destinations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    destination_type: Mapped[str] = mapped_column(Enum(*DESTINATION_TYPES), nullable=False)

    # Fernet-encrypted JSON blob containing all type-specific config
    config_json_encrypted: Mapped[str] = mapped_column(Text, nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_test_status: Mapped[str | None] = mapped_column(Enum(*TEST_STATUSES))
    last_test_message: Mapped[str | None] = mapped_column(Text)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_by: Mapped[str | None] = mapped_column(String(255))
    updated_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
    )

    __table_args__ = (
        Index("ix_workspace_destinations_workspace", "workspace_id", "is_active"),
        Index("ix_workspace_destinations_type", "workspace_id", "destination_type"),
    )

    # ------------------------------------------------------------------
    # Config access
    # ------------------------------------------------------------------

    def get_config(self) -> dict:
        """Return decrypted config. Only for server-side use — never send to client."""
        return decrypt_config(self.config_json_encrypted)

    def set_config(self, config: dict) -> None:
        """Validate and encrypt config."""
        self._validate_config(config)
        self.config_json_encrypted = encrypt_config(config)

    def get_masked_config(self) -> dict:
        """Return config with sensitive fields masked. Safe to send to client."""
        try:
            config = self.get_config()
            return mask_config(config, self.destination_type)
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Usage tracking
    # ------------------------------------------------------------------

    def record_usage(self) -> None:
        """Increment usage counter and update last_used_at. Call after successful delivery."""
        self.usage_count = (self.usage_count or 0) + 1
        self.last_used_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.add(self)

    def get_usage_summary(self) -> dict:
        """Return usage stats for the admin UI."""
        from app.models.query.skills import QuerySkill
        try:
            # Count distinct skills referencing this destination
            skills_using = _count_skills_using_destination(self.id, self.workspace_id)
        except Exception:
            skills_using = None
        return {
            "usage_count": self.usage_count,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "skills_using_count": skills_using,
        }

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self, include_masked_config: bool = True) -> dict[str, Any]:
        result = {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "name": self.name,
            "description": self.description,
            "destination_type": self.destination_type,
            "is_active": self.is_active,
            "last_tested_at": self.last_tested_at.isoformat() if self.last_tested_at else None,
            "last_test_status": self.last_test_status,
            "last_test_message": self.last_test_message,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "usage_count": self.usage_count,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "config_schema": DESTINATION_CONFIG_SCHEMAS.get(self.destination_type, {}),
        }
        if include_masked_config:
            result["config"] = self.get_masked_config()
        return result

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_config(self, config: dict) -> None:
        schema = DESTINATION_CONFIG_SCHEMAS.get(self.destination_type, {})
        required = schema.get("required", [])
        missing = [f for f in required if not config.get(f)]
        if missing:
            raise ValueError(f"Missing required config fields: {', '.join(missing)}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_skills_using_destination(destination_id: int, workspace_id: int) -> int:
    """
    Count distinct QuerySkill records that reference this destination_id
    anywhere in their config JSON.
    Uses a JSON search — adjust to your MySQL version if needed.
    """
    from app.models.query.skills import QuerySkill
    try:
        # MySQL 5.7+ JSON_SEARCH
        result = db.session.execute(
            db.text(
                "SELECT COUNT(*) FROM query_skills "
                "WHERE workspace_id = :ws AND is_active = 1 "
                "AND JSON_SEARCH(config_json, 'one', :dest_id) IS NOT NULL"
            ),
            {"ws": workspace_id, "dest_id": str(destination_id)},
        ).scalar()
        return int(result or 0)
    except Exception:
        return 0
