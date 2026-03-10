# app/adapters/analytics/mysql_metadata_provider.py
from __future__ import annotations

import logging
import re

from app.ports.metadata_provider_abc import MetadataProvider
from app.ports.sql_executor_abc import SQLExecutor

logger = logging.getLogger(__name__)

_IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")
_ID_LIKE_PATTERNS = ("id", "_id", "guid", "uuid", "k_", "sk_", "pk_", "_key", "identifier")
_COMPLEX_TYPES = {"blob", "binary", "json", "geometry"}
_STRING_TYPES = {"varchar", "char", "tinytext", "text", "mediumtext", "longtext"}


def _safe_ident(s: str) -> str:
    if not _IDENT_RE.fullmatch(s or ""):
        raise ValueError(f"Unsafe SQL identifier: {s!r}")
    return s


def _is_id_like(col_name: str) -> bool:
    n = col_name.lower()
    return any(n == p or n.endswith(p) or n.startswith(p) for p in _ID_LIKE_PATTERNS)


def _is_complex_type(dt: str) -> bool:
    return any(dt.lower().startswith(t) for t in _COMPLEX_TYPES)


def _is_string_type(dt: str) -> bool:
    return any(dt.lower().startswith(t) for t in _STRING_TYPES)


class MySQLMetadataProvider(MetadataProvider):
    """Discovers metadata from a MySQL analytics database via information_schema."""

    def __init__(self, *, executor: SQLExecutor) -> None:
        self._executor = executor

    def list_tables(self, catalog: str | None, schema: str) -> list[dict]:
        db = _safe_ident(schema)
        sql = f"""
SELECT TABLE_NAME AS table_name, TABLE_TYPE AS table_type, TABLE_COMMENT AS comment
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = '{db}'
ORDER BY TABLE_NAME
"""
        rows = self._executor.execute(sql)
        return [
            {
                "table_name": r["table_name"],
                "table_type": r.get("table_type", "BASE TABLE"),
                "comment": r.get("comment"),
            }
            for r in rows
        ]

    def list_columns(
        self,
        catalog: str | None,
        schema: str,
        table_names: list[str] | None = None,
    ) -> list[dict]:
        db = _safe_ident(schema)
        table_filter = ""
        if table_names:
            quoted = ", ".join(f"'{_safe_ident(t)}'" for t in table_names)
            table_filter = f"AND TABLE_NAME IN ({quoted})"
        sql = f"""
SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name,
       DATA_TYPE AS data_type, ORDINAL_POSITION AS ordinal_position,
       IS_NULLABLE AS is_nullable, COLUMN_COMMENT AS comment
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = '{db}' {table_filter}
ORDER BY TABLE_NAME, ORDINAL_POSITION
"""
        rows = self._executor.execute(sql)
        return [
            {
                "table_name": r["table_name"],
                "column_name": r["column_name"],
                "data_type": r.get("data_type"),
                "ordinal_position": int(r.get("ordinal_position") or 0),
                "is_nullable": str(r.get("is_nullable", "YES")).upper() not in ("NO", "0", "FALSE"),
                "comment": r.get("comment"),
            }
            for r in rows
        ]

    def list_schemas(self, catalog: str | None) -> list[str]:
        # MySQL has no catalog concept; the catalog parameter is intentionally ignored.
        sql = (
            "SELECT schema_name "
            "FROM information_schema.schemata "
            "ORDER BY schema_name"
        )
        rows = self._executor.execute(sql)
        return [row["schema_name"] for row in rows]

    def profile_table_columns(self, table_ref: str, columns: list[dict], options: dict) -> dict:
        row_cap = int(options.get("sample_row_cap", 200_000))
        per_col_limit = int(options.get("per_column_limit", 10))
        max_distinct = int(options.get("max_distinct_for_top_values", 250))
        only_strings = bool(options.get("profile_top_values_only_for_string_types", True))
        skip_id_like = bool(options.get("skip_top_values_for_id_like_cols", True))

        result: dict = {c["column_name"]: {"sample_error": None, "top_values": []} for c in columns}

        try:
            # Step 1: sample row count — MySQL uses LIMIT instead of TABLESAMPLE
            count_sql = (
                f"SELECT COUNT(*) AS row_count "
                f"FROM (SELECT 1 FROM {table_ref} LIMIT {row_cap}) _s"
            )
            count_rows = self._executor.execute(count_sql)
            sample_row_count = int((count_rows[0] or {}).get("row_count", 0)) if count_rows else 0

            # Step 2: one-pass null count + COUNT(DISTINCT …) aggregation
            agg_exprs = []
            for col in columns:
                cn = _safe_ident(col["column_name"])
                agg_exprs.append(
                    f"SUM(CASE WHEN `{cn}` IS NULL THEN 1 ELSE 0 END) AS `null_{cn}`"
                )
                agg_exprs.append(f"COUNT(DISTINCT `{cn}`) AS `dist_{cn}`")

            agg_sql = (
                f"SELECT {', '.join(agg_exprs)} "
                f"FROM (SELECT * FROM {table_ref} LIMIT {row_cap}) _s"
            )
            agg_rows = self._executor.execute(agg_sql)
            agg = agg_rows[0] if agg_rows else {}

            for col in columns:
                cn = col["column_name"]
                safe_cn = _safe_ident(cn)
                null_count = int(agg.get(f"null_{safe_cn}") or 0)
                approx_dist = int(agg.get(f"dist_{safe_cn}") or 0)
                null_pct = (null_count / sample_row_count) if sample_row_count else 0.0
                result[cn].update({
                    "null_count": null_count,
                    "null_pct": round(null_pct, 6),
                    "approx_distinct": approx_dist,
                    "sample_row_count": sample_row_count,
                })

        except Exception as exc:
            logger.exception(
                "MySQLMetadataProvider.profile_table_columns failed for %s", table_ref
            )
            for col in columns:
                result[col["column_name"]]["sample_error"] = str(exc)[:500]
            return result

        # Step 3: per-column top values (per-column error isolation)
        for col in columns:
            cn = col["column_name"]
            dtype = col.get("data_type", "")
            if _is_complex_type(dtype):
                continue
            if only_strings and not _is_string_type(dtype):
                continue
            if skip_id_like and _is_id_like(cn):
                continue
            if result[cn].get("approx_distinct", 0) > max_distinct:
                continue
            try:
                safe_cn = _safe_ident(cn)
                top_sql = (
                    f"SELECT CAST(`{safe_cn}` AS CHAR) AS val, COUNT(*) AS cnt "
                    f"FROM (SELECT * FROM {table_ref} LIMIT {row_cap}) _s "
                    f"WHERE `{safe_cn}` IS NOT NULL "
                    f"GROUP BY `{safe_cn}` ORDER BY cnt DESC LIMIT {per_col_limit}"
                )
                top_rows = self._executor.execute(top_sql)
                result[cn]["top_values"] = [str(r.get("val", "")) for r in top_rows]
            except Exception as exc:
                logger.warning(
                    "MySQL top-values failed for %s.%s: %s", table_ref, cn, exc
                )
                result[cn]["sample_error"] = str(exc)[:500]

        return result
