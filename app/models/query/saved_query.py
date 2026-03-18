"""
app/models/query/saved_query.py

Minimal read model for saved_query — used by the ownership service and
@require_ownership decorator.  Route handlers continue to use ForgeMetaSQL
for all reads and writes; this model exists solely for ownership lookups.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.semantic.semantic_registry import SemanticBase


class _QueryProperty:
    """Enables Model.query.filter_by(...) syntax using the shared DB session."""

    def __get__(self, obj, cls):
        from app.extensions import db as _db
        return _db.session.query(cls)


class SavedQuery(SemanticBase):
    __tablename__ = "saved_query"

    query = _QueryProperty()

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_shared: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_deleted: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
