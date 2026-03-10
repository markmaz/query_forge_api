from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort


@dataclass(frozen=True)
class _WorkspaceTableAccess:
    full_name: Optional[str]
    model_table_id: Optional[int]


class DomainColumnSampleReadService:
    """
    Reads cached sample metadata from model_column for a user-accessible workspace table.
    """

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def sample_column_values(
        self,
        *,
        workspace_id: str,
        user_id: str,
        workspace_table_id: int,
        column_name: str,
        limit: int = 10,
    ) -> Dict[str, Any]:
        safe_limit = int(limit)
        column = (column_name or "").strip()
        if not column:
            raise ForgeError("column_name is required", status_code=400)

        access = self._load_workspace_table_access(
            workspace_id=workspace_id,
            user_id=user_id,
            workspace_table_id=int(workspace_table_id),
        )

        if access.model_table_id is None:
            return self._base_response(
                workspace_table_id=workspace_table_id,
                full_name=access.full_name,
                model_table_id=None,
                column_name=column,
                limit=safe_limit,
                values=[],
                sample_stats=None,
                sample_ran_at=None,
                error="workspace_table is not mapped to a model_table",
            )

        row = self._load_model_column_sample(model_table_id=access.model_table_id, column_name=column)
        if row is None:
            return self._base_response(
                workspace_table_id=workspace_table_id,
                full_name=access.full_name,
                model_table_id=access.model_table_id,
                column_name=column,
                limit=safe_limit,
                values=[],
                sample_stats=None,
                sample_ran_at=None,
                error="model_column not found for this model_table_id + column_name",
            )

        sample_stats = _safe_json_load(row.get("sample_stats_json"))
        sample_ran_at = row.get("sample_ran_at")
        sample_error = row.get("sample_error")

        if sample_error:
            return self._base_response(
                workspace_table_id=workspace_table_id,
                full_name=access.full_name,
                model_table_id=access.model_table_id,
                column_name=column,
                limit=safe_limit,
                values=[],
                sample_stats=sample_stats,
                sample_ran_at=sample_ran_at,
                error=sample_error,
            )

        values = _safe_json_load(row.get("sample_values_json")) or []
        if not isinstance(values, list):
            values = []

        return self._base_response(
            workspace_table_id=workspace_table_id,
            full_name=access.full_name,
            model_table_id=access.model_table_id,
            column_name=column,
            limit=safe_limit,
            values=values[:safe_limit],
            sample_stats=sample_stats,
            sample_ran_at=sample_ran_at,
            error=None,
        )

    def _load_workspace_table_access(self, *, workspace_id: str, user_id: str, workspace_table_id: int) -> _WorkspaceTableAccess:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              wt.id,
              wt.workspace_id,
              wt.full_name,
              wt.model_table_id
            FROM workspace_table wt
            WHERE wt.id = :wtid
              AND wt.workspace_id = :ws
              AND wt.exists_in_dbx = 1
              AND EXISTS (
                SELECT 1
                FROM user_domain_mapping udm
                JOIN domain d
                  ON d.id = udm.domain_id
                 AND d.workspace_id = :ws
                 AND d.is_active = 1
                JOIN domain_workspace_table dwt
                  ON dwt.domain_id = d.id
                 AND dwt.workspace_table_id = wt.id
                WHERE udm.user_id = :uid
                  AND udm.can_read = 1
              )
            LIMIT 1
            """,
            {"wtid": int(workspace_table_id), "ws": workspace_id, "uid": user_id},
        )
        row = rows[0] if rows else None
        if not row:
            raise ForgeError("workspace_table not found (or no access)", status_code=404)

        model_table_id = row.get("model_table_id")
        return _WorkspaceTableAccess(
            full_name=row.get("full_name"),
            model_table_id=int(model_table_id) if model_table_id is not None else None,
        )

    def _load_model_column_sample(self, *, model_table_id: int, column_name: str) -> Optional[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              mc.sample_values_json,
              mc.sample_stats_json,
              mc.sample_ran_at,
              mc.sample_error
            FROM model_column mc
            WHERE mc.model_table_id = :mtid
              AND mc.column_name = :col
              AND mc.is_active = 1
            LIMIT 1
            """,
            {"mtid": int(model_table_id), "col": column_name},
        )
        return rows[0] if rows else None

    def _base_response(
        self,
        *,
        workspace_table_id: int,
        full_name: Optional[str],
        model_table_id: Optional[int],
        column_name: str,
        limit: int,
        values: Any,
        sample_stats: Any,
        sample_ran_at: Any,
        error: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "workspace_table_id": int(workspace_table_id),
            "full_name": full_name,
            "model_table_id": model_table_id,
            "column_name": column_name,
            "limit": int(limit),
            "values": values,
            "sample_stats": sample_stats,
            "sample_ran_at": sample_ran_at,
            "error": error,
        }


def _safe_json_load(s: Optional[str]) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None
