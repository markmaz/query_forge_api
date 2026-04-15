from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.query_tree.saved_query_share_models import ShareContext
from app.services.query_tree.saved_query_share_policy import (
    build_share_list_item,
    build_share_payload,
    require_field,
)
from app.services.query_tree.saved_query_share_repository import SavedQueryShareRepository


class SavedQueryShareService:
    """Share/unshare/list ACL records for saved queries."""

    def __init__(self, *, workspace_id: str, user_id: str, sql: Optional[ForgeQueryPort] = None):
        if not workspace_id:
            raise ForgeError("workspace_id is required", status_code=400)
        if not user_id:
            raise ForgeError("user_id is required", status_code=400)

        self._ctx = ShareContext(workspace_id=workspace_id, user_id=user_id)
        self._sql = sql or ForgeMetaSQL()
        self._repo = SavedQueryShareRepository(ctx=self._ctx, sql=self._sql)
        self._ws = workspace_id

    def share_to_workspace(self, *, query_id: str, can_edit: bool = False) -> Dict[str, Any]:
        query_id = require_field(query_id, "query_id")
        self._assert_query_owner(query_id)

        permission = "WRITE" if can_edit else "READ"
        acl = self._upsert_acl(
            saved_query_id=query_id,
            principal_type="WORKSPACE",
            principal_id=self._ctx.workspace_id,
            permission=permission,
        )
        return build_share_payload(
            acl_id=acl["id"],
            query_id=query_id,
            principal_type="WORKSPACE",
            principal_id=self._ctx.workspace_id,
            permission=permission,
        )

    def unshare(self, *, query_id: str) -> Dict[str, Any]:
        query_id = require_field(query_id, "query_id")
        self._assert_query_owner(query_id)
        removed = self._repo.remove_acl(
            query_id=query_id,
            principal_type="WORKSPACE",
            principal_id=self._ctx.workspace_id,
        )
        return {"queryId": query_id, "shareKind": "WORKSPACE", "removed": (removed or 0) > 0}

    def list_shares(self, *, query_id: str) -> Dict[str, Any]:
        query_id = require_field(query_id, "query_id")
        self._assert_query_owner(query_id)

        rows = self._repo.list_query_shares(query_id=query_id)
        return {
            "queryId": query_id,
            "shares": [build_share_list_item(row) for row in rows],
        }

    def _assert_query_owner(self, query_id: str) -> None:
        if not self._repo.owned_query_exists(query_id=query_id):
            raise ForgeError("Saved query not found", status_code=404)

    def _upsert_acl(self, *, saved_query_id: str, principal_type: str, principal_id: str, permission: str) -> Dict[str, Any]:
        existing = self._find_acl(saved_query_id=saved_query_id, principal_type=principal_type, principal_id=principal_id)
        if existing:
            self._repo.update_acl_permission(acl_id=existing["id"], permission=permission)
            existing["permission"] = permission
            return existing

        acl_id = str(uuid.uuid4())
        self._repo.insert_acl(
            acl_id=acl_id,
            saved_query_id=saved_query_id,
            principal_type=principal_type,
            principal_id=principal_id,
            permission=permission,
        )
        return {"id": acl_id, "permission": permission}

    def _find_acl(self, *, saved_query_id: str, principal_type: str, principal_id: str) -> Optional[Dict[str, Any]]:
        return self._repo.fetch_acl(
            saved_query_id=saved_query_id,
            principal_type=principal_type,
            principal_id=principal_id,
        )


def _req(v: Any, field: str) -> str:
    return require_field(v, field)
