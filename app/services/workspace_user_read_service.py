from __future__ import annotations

from typing import Any

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.services.user.workspace_user_query import (
    build_workspace_user_list_query,
    validate_workspace_user_list_args,
)
from app.services.user.workspace_user_serializer import serialize_workspace_user_row


class WorkspaceUserReadService:
    ACTIVE_STATUSES = ("Active", "Invited")

    def __init__(self, *, sql: ForgeQueryPort | None = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def list_workspace_users(
        self,
        *,
        workspace_id: str,
        q: str | None = None,
        limit: int = 5000,
        offset: int = 0,
        include_inactive: bool = True,
    ) -> list[dict[str, Any]]:
        workspace_value, limit_value, offset_value = validate_workspace_user_list_args(
            workspace_id=workspace_id,
            limit=limit,
            offset=offset,
        )
        query, params = build_workspace_user_list_query(
            workspace_id=workspace_value,
            q=q,
            limit=limit_value,
            offset=offset_value,
            include_inactive=include_inactive,
        )
        rows = self._sql.execute_query_mappings(query, params)
        return [self._serialize_row(row) for row in rows]

    def _serialize_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return serialize_workspace_user_row(row)
