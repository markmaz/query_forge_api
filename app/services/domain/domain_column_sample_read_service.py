from __future__ import annotations

from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.domain.column_sample.domain_column_sample_access import load_workspace_table_access
from app.services.domain.column_sample.domain_column_sample_presenter import (
    base_response,
    safe_json_load,
)
from app.services.domain.column_sample.domain_column_sample_repository import load_workspace_column_sample


class DomainColumnSampleReadService:
    """
    Reads cached sample metadata from workspace_column for a user-accessible workspace table.
    """

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None, metadata_mode: Optional[str] = None) -> None:
        del metadata_mode
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

        row = self._load_workspace_column_sample(
            workspace_table_id=access.workspace_table_id,
            column_name=column,
        )
        if row is None:
            return self._base_response(
                workspace_table_id=workspace_table_id,
                full_name=access.full_name,
                model_table_id=None,
                column_name=column,
                limit=safe_limit,
                values=[],
                sample_stats=None,
                sample_ran_at=None,
                error="workspace_column not found for this workspace_table_id + column_name",
            )

        sample_stats = _safe_json_load(row.get("sample_stats_json"))
        sample_ran_at = row.get("sample_ran_at")
        sample_error = row.get("sample_error")

        if sample_error:
            return self._base_response(
                workspace_table_id=workspace_table_id,
                full_name=access.full_name,
                model_table_id=None,
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
            model_table_id=None,
            column_name=column,
            limit=safe_limit,
            values=values[:safe_limit],
            sample_stats=sample_stats,
            sample_ran_at=sample_ran_at,
            error=None,
        )

    def _load_workspace_table_access(self, *, workspace_id: str, user_id: str, workspace_table_id: int):
        return load_workspace_table_access(
            sql=self._sql,
            workspace_id=workspace_id,
            user_id=user_id,
            workspace_table_id=workspace_table_id,
        )

    def _load_workspace_column_sample(self, *, workspace_table_id: int, column_name: str) -> Optional[Dict[str, Any]]:
        return load_workspace_column_sample(
            sql=self._sql,
            workspace_table_id=workspace_table_id,
            column_name=column_name,
        )

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
        return base_response(
            workspace_table_id=workspace_table_id,
            full_name=full_name,
            model_table_id=model_table_id,
            column_name=column_name,
            limit=limit,
            values=values,
            sample_stats=sample_stats,
            sample_ran_at=sample_ran_at,
            error=error,
        )


def _safe_json_load(s: Optional[str]) -> Any:
    return safe_json_load(s)
