from __future__ import annotations

from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.services.domain.builder_feed import (
    BuilderFeedQuery,
    BuilderTableFeedService,
    ColumnNamePolicyService,
    build_builder_feed_params,
    build_builder_feed_sql,
    camelize_builder_row,
    qf_json_safe,
    qf_snake_to_camel,
)
from app.services.shared.jsonify import serialize_result_rows


def _qf_snake_to_camel(s: str) -> str:
    return qf_snake_to_camel(s)


def _qf_json_safe(v: Any) -> Any:
    return qf_json_safe(v)


def _camelize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return camelize_builder_row(row)


class BuilderColumnFeedService:
    """
    Builder feed: only columns available through user's readable domains.
    Uses workspace metadata as the source of truth.
    """

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None, metadata_mode: Optional[str] = None) -> None:
        del metadata_mode
        self._sql = sql or ForgeMetaSQL()
        self._table_feed = BuilderTableFeedService(sql=self._sql)
        self._column_name_policy = ColumnNamePolicyService(sql=self._sql)

    def list_domain_tables(self, *, workspace_id: str, user_id: str, domain_id: Optional[int]) -> Dict[str, Any]:
        return self._table_feed.list_domain_tables(
            workspace_id=workspace_id,
            user_id=user_id,
            domain_id=domain_id,
        )

    def list_available_columns(self, q: BuilderFeedQuery) -> Dict[str, Any]:
        params = self._build_params(q)
        policy = self._get_column_name_policy(q.workspace_id, q.domain_id)
        sql_pack = self._build_policy_sql(policy)

        total_rows = self._sql.execute_query(sql_pack.qf_count_sql, params)
        total = int(total_rows[0][0]) if total_rows else 0

        rows = self._sql.execute_query_mappings(sql_pack.rows_sql, params)
        camel_rows = []
        for row in rows:
            shaped = _camelize_row(dict(row))
            shaped["modelColumnId"] = shaped.get("workspaceColumnId")
            camel_rows.append(shaped)

        return {
            "rows": serialize_result_rows(camel_rows),
            "total": total,
            "limit": params["limit"],
            "offset": params["offset"],
            "columnNamePolicy": policy,
        }

    def _build_params(self, q: BuilderFeedQuery) -> Dict[str, Any]:
        return build_builder_feed_params(q)

    def _build_policy_sql(self, policy: str):
        sql_pack = build_builder_feed_sql(policy)
        return type("_FeedSqlCompat", (), {"qf_count_sql": sql_pack.count_sql, "rows_sql": sql_pack.rows_sql})()

    def _get_column_name_policy(self, workspace_id: str, domain_id: Optional[int]) -> str:
        return self._column_name_policy.get_policy(workspace_id=workspace_id, domain_id=domain_id)
