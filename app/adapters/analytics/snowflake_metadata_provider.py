# app/adapters/analytics/snowflake_metadata_provider.py
from __future__ import annotations

import logging
import re

from app.ports.metadata_provider_abc import MetadataProvider
from app.ports.sql_executor_abc import SQLExecutor

logger = logging.getLogger(__name__)

_IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")
_ID_LIKE_PATTERNS = ("id", "_id", "guid", "uuid", "k_", "sk_", "pk_", "_key", "identifier")
_COMPLEX_TYPES = {"binary", "variant", "object", "array"}
_STRING_TYPES = {"varchar", "char", "nvarchar", "nchar", "text", "string"}


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


def _normalize_row(row: dict) -> dict:
    """Return a case-insensitive view by lowercasing keys."""
    return {str(k).lower(): v for k, v in (row or {}).items()}


class SnowflakeMetadataProvider(MetadataProvider):
    """Discovers metadata from Snowflake INFORMATION_SCHEMA."""

    def __init__(self, *, executor: SQLExecutor) -> None:
        self._executor = executor

    def list_tables(self, catalog: str | None, schema: str) -> list[dict]:
        schema = _safe_ident(schema)
        db_filter = f"TABLE_CATALOG = '{_safe_ident(catalog)}' AND " if catalog else ""
        sql = f"""
SELECT TABLE_NAME AS table_name, TABLE_TYPE AS table_type, COMMENT AS comment
FROM INFORMATION_SCHEMA.TABLES
WHERE {db_filter}TABLE_SCHEMA = '{schema}'
ORDER BY TABLE_NAME
"""
        rows = self._executor.execute(sql)
        result: list[dict] = []
        for row in rows:
            r = _normalize_row(row)
            table_name = str(r.get("table_name") or "").strip()
            if not table_name:
                continue
            result.append(
                {
                    "table_name": table_name,
                    "table_type": r.get("table_type", "BASE TABLE"),
                    "comment": r.get("comment"),
                }
            )
        return result

    def list_columns(
        self,
        catalog: str | None,
        schema: str,
        table_names: list[str] | None = None,
    ) -> list[dict]:
        schema = _safe_ident(schema)
        db_filter = f"TABLE_CATALOG = '{_safe_ident(catalog)}' AND " if catalog else ""
        table_filter = ""
        if table_names:
            quoted = ", ".join(f"'{_safe_ident(t)}'" for t in table_names)
            table_filter = f"AND TABLE_NAME IN ({quoted})"
        sql = f"""
SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name,
       DATA_TYPE AS data_type, ORDINAL_POSITION AS ordinal_position,
       IS_NULLABLE AS is_nullable, COMMENT AS comment
FROM INFORMATION_SCHEMA.COLUMNS
WHERE {db_filter}TABLE_SCHEMA = '{schema}' {table_filter}
ORDER BY TABLE_NAME, ORDINAL_POSITION
"""
        rows = self._executor.execute(sql)
        result: list[dict] = []
        for row in rows:
            r = _normalize_row(row)
            table_name = str(r.get("table_name") or "").strip()
            column_name = str(r.get("column_name") or "").strip()
            if not table_name or not column_name:
                continue
            result.append(
                {
                    "table_name": table_name,
                    "column_name": column_name,
                    "data_type": r.get("data_type"),
                    "ordinal_position": int(r.get("ordinal_position") or 0),
                    "is_nullable": str(r.get("is_nullable", "YES")).upper() not in ("NO", "0", "FALSE"),
                    "comment": r.get("comment"),
                }
            )
        return result

    def list_schemas(self, catalog: str | None) -> list[str]:
        if catalog:
            catalog_prefix = f'"{_safe_ident(catalog)}".'
        else:
            catalog_prefix = ""
        sql = (
            f"SELECT schema_name "
            f"FROM {catalog_prefix}information_schema.schemata "
            f"ORDER BY schema_name"
        )
        rows = self._executor.execute(sql)
        names: list[str] = []
        for row in rows:
            r = _normalize_row(row)
            schema_name = str(r.get("schema_name") or "").strip()
            if schema_name:
                names.append(schema_name)
        return sorted(names)

    def profile_table_columns(
        self,
        table_ref: str,
        columns: list[dict],
        options: dict,
    ) -> dict:
        sample_pct = float(options.get("sample_percent", 0.10)) * 100
        row_cap = int(options.get("sample_row_cap", 200_000))
        per_col_limit = int(options.get("per_column_limit", 10))
        max_distinct = int(options.get("max_distinct_for_top_values", 250))
        only_strings = bool(options.get("profile_top_values_only_for_string_types", True))
        skip_id_like = bool(options.get("skip_top_values_for_id_like_cols", True))

        result: dict = {c["column_name"]: {"sample_error": None, "top_values": []} for c in columns}

        try:
            # Step 1: sample row count — Snowflake SAMPLE syntax: SAMPLE (N) where N is a percentage
            count_sql = f"""
SELECT COUNT(*) AS row_count
FROM (SELECT * FROM {table_ref} SAMPLE ({sample_pct}) LIMIT {row_cap}) _s
"""
            count_rows = self._executor.execute(count_sql)
            count_row = _normalize_row(count_rows[0]) if count_rows else {}
            sample_row_count = int(count_row.get("row_count") or 0)

            # Step 2: one-pass null + approx_count_distinct aggregation across all columns
            agg_exprs = []
            for col in columns:
                cn = _safe_ident(col["column_name"])
                agg_exprs.append(
                    f'SUM(CASE WHEN "{cn}" IS NULL THEN 1 ELSE 0 END) AS "null_{cn}"'
                )
                agg_exprs.append(f'APPROX_COUNT_DISTINCT("{cn}") AS "dist_{cn}"')

            agg_sql = f"""
SELECT {', '.join(agg_exprs)}
FROM (SELECT * FROM {table_ref} SAMPLE ({sample_pct}) LIMIT {row_cap}) _s
"""
            agg_rows = self._executor.execute(agg_sql)
            agg = _normalize_row(agg_rows[0]) if agg_rows else {}

            for col in columns:
                cn = col["column_name"]
                safe_cn = _safe_ident(cn)
                null_count = int(agg.get(f"null_{safe_cn}".lower()) or 0)
                approx_dist = int(agg.get(f"dist_{safe_cn}".lower()) or 0)
                null_pct = (null_count / sample_row_count) if sample_row_count else 0.0
                result[cn].update({
                    "null_count": null_count,
                    "null_pct": round(null_pct, 6),
                    "approx_distinct": approx_dist,
                    "sample_row_count": sample_row_count,
                })

        except Exception as exc:
            logger.exception(
                "SnowflakeMetadataProvider.profile_table_columns failed for %s", table_ref
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

            try:
                safe_cn = _safe_ident(cn)
                if result[cn].get("approx_distinct", 0) > max_distinct:
                    value_sql = f"""
SELECT DISTINCT CAST("{safe_cn}" AS VARCHAR) AS val
FROM (SELECT * FROM {table_ref} SAMPLE ({sample_pct}) LIMIT {row_cap}) _s
WHERE "{safe_cn}" IS NOT NULL
LIMIT {per_col_limit}
"""
                else:
                    value_sql = f"""
SELECT CAST("{safe_cn}" AS VARCHAR) AS val, COUNT(*) AS cnt
FROM (SELECT * FROM {table_ref} SAMPLE ({sample_pct}) LIMIT {row_cap}) _s
WHERE "{safe_cn}" IS NOT NULL
GROUP BY "{safe_cn}" ORDER BY cnt DESC LIMIT {per_col_limit}
"""
                top_rows = self._executor.execute(value_sql)
                top_values: list[str] = []
                for row in top_rows:
                    normalized = _normalize_row(row)
                    top_values.append(str(normalized.get("val", "")))
                result[cn]["top_values"] = top_values
            except Exception as exc:
                logger.warning(
                    "Snowflake value sampling failed for %s.%s: %s", table_ref, cn, exc
                )
                result[cn]["sample_error"] = str(exc)[:500]

        return result
