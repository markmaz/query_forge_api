from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.ports.sql_executor import SQLExecutor
from app.services.shared.jsonify import jsonify_rows


@dataclass(frozen=True)
class BuilderFeedQuery:
    workspace_id: str
    user_id: str

    domain_id: Optional[int] = None
    table_q: Optional[str] = None
    column_q: Optional[str] = None
    variant_code: Optional[str] = None
    only_qe: Optional[bool] = None

    limit: int = 1000
    offset: int = 0


def _snake_to_camel(s: str) -> str:
    parts = s.split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:] if p)


def _json_safe(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        # if you want timezone-aware, do it at write-time; this keeps your current style
        return v.isoformat(timespec="seconds")
    return v


def _camelize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in row.items():
        out[_snake_to_camel(k)] = _json_safe(v)
    return out


class BuilderColumnFeedService:
    """
    Builder feed: ONLY columns available to the user through domain membership.
    Overlays dictionary metadata from model_column.
    Adds pagination metadata: total, limit, offset.
    """

    def __init__(self, *, sql: Optional[SQLExecutor] = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

    def list_domain_tables(self, *, workspace_id: str, user_id: str, domain_id: Optional[int]) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "ws": workspace_id,
            "user_id": user_id,
            "domain_id": int(domain_id) if domain_id is not None else None,
        }

        sql = """
            SELECT DISTINCT
              wt.id            AS workspace_table_id,
              wt.model_table_id,
              mt.name          AS model_table_name,
              wt.catalog_name,
              wt.schema_name,
              wt.table_name,
              wt.full_name,
              wt.variant_code,
              wt.is_qe
            FROM user_domain_mapping udm
            JOIN domain d
              ON d.id = udm.domain_id
            AND d.workspace_id = :ws
            AND d.is_active = 1
            AND udm.user_id = :user_id
            AND udm.can_read = 1
            AND (:domain_id IS NULL OR d.id = :domain_id)
            JOIN domain_workspace_table dwt
              ON dwt.domain_id = d.id
            JOIN workspace_table wt
              ON wt.id = dwt.workspace_table_id
            AND wt.workspace_id = :ws
            AND wt.exists_in_dbx = 1
            LEFT JOIN model_table mt
              ON mt.id = wt.model_table_id
            ORDER BY COALESCE(mt.name, wt.table_name), wt.full_name
        """

        rows = self._sql.execute_query_mappings(sql, params)
        return {"rows": jsonify_rows([dict(r) for r in rows])}

    def list_available_columns(self, q: BuilderFeedQuery) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "ws": q.workspace_id,
            "user_id": q.user_id,
            "domain_id": int(q.domain_id) if q.domain_id is not None else None,
            "table_q": (q.table_q or "").strip() or None,
            "column_q": (q.column_q or "").strip() or None,
            "variant_code": (q.variant_code or "").strip() or None,
            "only_qe": None if q.only_qe is None else (1 if q.only_qe else 0),
            "limit": int(q.limit),
            "offset": int(q.offset),
        }

        column_name_policy = self._get_column_name_policy(q.workspace_id, q.domain_id)

        base_cte = """
          WITH base AS (
            SELECT DISTINCT
              wt.id                      AS workspace_table_id,
              wt.full_name,
              wt.table_name              AS base_table_name,
              wt.schema_name,
              wt.catalog_name,
              wt.variant_code,
              wt.is_qe,
              wt.exists_in_dbx,
              wt.last_seen_at,

              dwt.table_alias,
              dwt.is_primary,
              dwt.sort_order,

              d.id                       AS domain_id,
              d.name                     AS domain_name,
              d.column_name_policy,

              wc.id                      AS workspace_column_id,
              wc.column_name,
              wc.data_type,
              wc.nullable,
              wc.ordinal_position,

              mc.id                      AS model_column_id,
              mc.description             AS description,

              -- column-level samples
              mc.sample_values_json      AS sample_values_json,
              mc.sample_stats_json       AS sample_stats_json,
              mc.sample_ran_at           AS sample_ran_at,
              mc.sample_error            AS sample_error

            FROM user_domain_mapping udm
            JOIN domain d
              ON d.id = udm.domain_id
            AND d.workspace_id = :ws
            AND d.is_active = 1
            AND udm.user_id = :user_id
            AND udm.can_read = 1
            AND (:domain_id IS NULL OR d.id = :domain_id)

            JOIN domain_workspace_table dwt
              ON dwt.domain_id = d.id

            JOIN workspace_table wt
              ON wt.id = dwt.workspace_table_id
            AND wt.workspace_id = :ws
            AND wt.exists_in_dbx = 1
            AND (:variant_code IS NULL OR wt.variant_code = :variant_code)
            AND (:only_qe IS NULL OR wt.is_qe = :only_qe)

            JOIN workspace_column wc
              ON wc.workspace_table_id = wt.id

            LEFT JOIN model_column mc
              ON mc.model_table_id = wt.model_table_id
            AND mc.column_name = wc.column_name
            AND mc.is_active = 1
            AND mc.is_missing_in_source = 0

            WHERE
              (
                :table_q IS NULL OR
                wt.full_name LIKE CONCAT('%', :table_q, '%') OR
                wt.table_name LIKE CONCAT('%', :table_q, '%') OR
                dwt.table_alias LIKE CONCAT('%', :table_q, '%')
              )
              AND (
                :column_q IS NULL OR
                wc.column_name LIKE CONCAT('%', :column_q, '%') OR
                mc.description LIKE CONCAT('%', :column_q, '%')
              )
          )
          """

        if column_name_policy == "SHOW_ALL_QUALIFIED":
            count_sql = base_cte + """
              SELECT COUNT(*) AS total
              FROM base
              """

            rows_sql = base_cte + """
              SELECT
                b.*,
                CONCAT(COALESCE(b.table_alias, b.base_table_name), '.', b.column_name) AS qualified_name,
                CONCAT(COALESCE(b.table_alias, b.base_table_name), ' -> ', b.column_name) AS column_label
              FROM base b
              ORDER BY
                CASE WHEN b.is_primary = 1 THEN 0 ELSE 1 END,
                b.sort_order,
                b.full_name,
                b.ordinal_position
              LIMIT :limit OFFSET :offset
              """
        else:
            base_cte = base_cte + """
              , ranked AS (
                SELECT
                  b.*,
                  ROW_NUMBER() OVER (
                    PARTITION BY b.domain_id, b.column_name
                    ORDER BY
                      b.is_primary DESC,
                      b.sort_order ASC,
                      b.ordinal_position ASC,
                      b.workspace_table_id ASC
                  ) AS rn
                FROM base b
              )
              """

            count_sql = base_cte + """
              SELECT COUNT(*) AS total
              FROM ranked
              WHERE rn = 1
              """

            rows_sql = base_cte + """
              SELECT
                r.*,
                COUNT(*) OVER (PARTITION BY r.domain_id, r.column_name) AS column_name_count,
                CONCAT(COALESCE(r.table_alias, r.base_table_name), '.', r.column_name) AS qualified_name,
                CONCAT(COALESCE(r.table_alias, r.base_table_name), ' -> ', r.column_name) AS column_label,
                r.column_name AS collision_group_key,
                CASE
                  WHEN COUNT(*) OVER (PARTITION BY r.domain_id, r.column_name) > 1 AND r.is_primary = 1
                  THEN 1 ELSE 0
                END AS is_default
              FROM ranked r
              WHERE r.rn = 1
              ORDER BY
                CASE WHEN r.is_primary = 1 THEN 0 ELSE 1 END,
                r.sort_order,
                r.full_name,
                r.ordinal_position
              LIMIT :limit OFFSET :offset
              """

        total_rows = self._sql.execute_query(count_sql, params)
        total = int(total_rows[0][0]) if total_rows else 0
        rows = self._sql.execute_query_mappings(rows_sql, params)

        # ✅ camelCase + JSON-safe
        camel_rows = [_camelize_row(dict(r)) for r in rows]

        return {
            "rows": jsonify_rows(camel_rows),
            "total": total,
            "limit": params["limit"],
            "offset": params["offset"],
            "columnNamePolicy": column_name_policy,
        }

    def _get_column_name_policy(self, workspace_id: str, domain_id: Optional[int]) -> str:
        if not domain_id:
            return "DEDUP_PRIMARY_FIRST"

        sql = """
            SELECT column_name_policy
            FROM domain
            WHERE id = :did AND workspace_id = :ws AND is_active = 1
            LIMIT 1
            """
        rows = self._sql.execute_query_mappings(sql, {"did": int(domain_id), "ws": workspace_id})
        row = rows[0] if rows else None
        if not row:
            return "DEDUP_PRIMARY_FIRST"
        val = (row.get("column_name_policy") or "DEDUP_PRIMARY_FIRST").strip().upper()
        return val if val in {"DEDUP_PRIMARY_FIRST", "SHOW_ALL_QUALIFIED"} else "DEDUP_PRIMARY_FIRST"
