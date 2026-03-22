"""
app/models/rbac.py

SQLAlchemy models for the QueryForge RBAC system.

Role resolution rules (enforced in decorators, not models):
  super_admin       → bypass all checks
  workspace_admin   → bypass feature checks + implies all feature :user roles
  feature:admin     → implies feature:user for that feature
  feature:user      → explicit access to that feature

Seam notes:
  db     — app.extensions._DB shim (DeclarativeBase + scoped_session)
  query  — use db.session.query(Model) not Model.query (no Flask-SQLAlchemy)
  FKs    — users.user_id VARCHAR(255), workspace.id VARCHAR(128)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db


# ---------------------------------------------------------------------------
# Query descriptor
# ---------------------------------------------------------------------------


class _QueryProperty:
    """Enables Model.query.filter_by(...) syntax on the custom _DB shim."""

    def __get__(self, obj, cls):
        from app.extensions import db as _db
        return _db.session.query(cls)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GLOBAL_ROLES = ("super_admin", "library_admin")

FEATURE_KEYS = (
    "catalog",
    "workspaces",
    "forge_match",
    "forge_insights",
    "query_studio",
    "skills",
    "planner",
    "semantic",
    "ingestion",
    "exports",
    "vector",
    "ai",
    "system",
)

ALL_ROLE_NAMES = (
    "super_admin",
    "library_admin",
    "workspace_admin",
    *[f"{f}:admin" for f in FEATURE_KEYS],
    *[f"{f}:user" for f in FEATURE_KEYS],
)

ROLE_DEFINITIONS = (
    {
        "name": "super_admin",
        "display_name": "Super Admin",
        "description": "Global administrator with full platform access.",
        "feature_key": None,
        "is_system": True,
    },
    {
        "name": "library_admin",
        "display_name": "Library Admin",
        "description": "Can publish, create, move, rename, and delete shared library queries and folders.",
        "feature_key": None,
        "is_system": True,
    },
    {
        "name": "workspace_admin",
        "display_name": "Workspace Admin",
        "description": "Administrator for workspace-scoped management operations.",
        "feature_key": None,
        "is_system": True,
    },
    *[
        {
            "name": f"{feature_key}:{role_suffix}",
            "display_name": f"{feature_key.replace('_', ' ').title()} {role_suffix.title()}",
            "description": (
                f"System role granting {role_suffix} access to the {feature_key} feature."
            ),
            "feature_key": feature_key,
            "is_system": True,
        }
        for feature_key in FEATURE_KEYS
        for role_suffix in ("admin", "user")
    ],
)


# ---------------------------------------------------------------------------
# Role
# ---------------------------------------------------------------------------


class UserRecord(db.Model):
    """Minimal ORM anchor for the existing users table.

    RBAC writes reference users.user_id via foreign keys, so the table needs to
    exist in SQLAlchemy metadata even though the rest of the app uses raw SQL or
    Pydantic models for user reads.
    """

    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)


class WorkspaceRecord(db.Model):
    """Minimal ORM anchor for the existing workspace table."""

    __tablename__ = "workspace"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)


class Role(db.Model):
    __tablename__ = "roles"

    query = _QueryProperty()

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500))
    feature_key: Mapped[str | None] = mapped_column(String(64))
    is_system: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    user_roles: Mapped[list[UserRole]] = relationship(
        "UserRole", back_populates="role", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "feature_key": self.feature_key,
            "is_system": self.is_system,
        }

    @classmethod
    def get_by_name(cls, name: str) -> "Role | None":
        return db.session.query(cls).filter_by(name=name).first()


# ---------------------------------------------------------------------------
# UserRole
# ---------------------------------------------------------------------------


class UserRole(db.Model):
    __tablename__ = "user_roles"

    query = _QueryProperty()

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # user_id is VARCHAR(255) matching users.user_id — not an int FK
    user_id: Mapped[str] = mapped_column(
        String(255), db.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[str | None] = mapped_column(
        String(128), db.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=True
    )
    role_id: Mapped[int] = mapped_column(
        Integer, db.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    granted_by: Mapped[str | None] = mapped_column(String(255))
    granted_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    role: Mapped[Role] = relationship("Role", back_populates="user_roles")

    __table_args__ = (
        UniqueConstraint("user_id", "workspace_id", "role_id", name="uq_user_role_workspace"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "workspace_id": self.workspace_id,
            "role_id": self.role_id,
            "role_name": self.role.name if self.role else None,
            "granted_by": self.granted_by,
            "granted_at": self.granted_at.isoformat() if self.granted_at else None,
        }


# ---------------------------------------------------------------------------
# WorkspaceFeature
# ---------------------------------------------------------------------------


class WorkspaceFeature(db.Model):
    __tablename__ = "workspace_features"

    query = _QueryProperty()

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # workspace_id is VARCHAR(128) matching workspace.id — not an int FK
    workspace_id: Mapped[str] = mapped_column(
        String(128), db.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    )
    feature_key: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    granted_by: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = (
        UniqueConstraint("workspace_id", "feature_key", name="uq_workspace_feature"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "workspace_id": self.workspace_id,
            "feature_key": self.feature_key,
            "is_active": self.is_active,
            "granted_at": self.granted_at.isoformat() if self.granted_at else None,
        }

    @classmethod
    def is_feature_active(cls, workspace_id: str, feature_key: str) -> bool:
        row = db.session.query(cls).filter_by(
            workspace_id=workspace_id,
            feature_key=feature_key,
            is_active=True,
        ).first()
        return row is not None
