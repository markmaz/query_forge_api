# app/adapters/analytics/databricks_metadata_provider.py
from __future__ import annotations

import logging
import re

from app.ports.metadata_provider_abc import MetadataProvider
from app.ports.sql_executor_abc import SQLExecutor

logger = logging.getLogger(__name__)

_IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")

_ID_LIKE_PATTERNS = ("id", "_id", "guid", "uuid", "k_", "sk_", "pk_", "_key", "identifier")
_COMPLEX_TYPES = {"binary", "blob", "variant", "map", "array", "struct"}
_STRING_TYPES = {"string", "varchar", "char", "text", "nvarchar", "nchar"}
METADATA_FALLBACK_ERRORS = (OSError, RuntimeError, TypeError, ValueError)


def _is_id_like(col_name: str) -> bool:
    name = col_name.lower()
    return any(
        name == p or name.endswith(p) or name.startswith(p)
        for p in _ID_LIKE_PATTERNS
    )


def _is_complex_type(data_type: str) -> bool:
    return any(data_type.lower().startswith(t) for t in _COMPLEX_TYPES)


def _is_string_type(data_type: str) -> bool:
    return any(data_type.lower().startswith(t) for t in _STRING_TYPES)


def _safe_ident(s: str) -> str:
    if not _IDENT_RE.fullmatch(s or ""):
        raise ValueError(f"Unsafe SQL identifier: {s!r}")
    return s


class DatabricksMetadataProvider(MetadataProvider):
    """Discovers metadata from Databricks Unity Catalog information_schema."""

    def __init__(self, *, executor: SQLExecutor) -> None:
        self._executor = executor

    def list_tables(self, catalog: str | None, schema: str) -> list[dict]:
        schema = _safe_ident(schema)
        if catalog:
            catalog = _safe_ident(catalog)
            catalog_filter = f"AND table_catalog = '{catalog}'"
        else:
            catalog_filter = ""

        sql = f"""
SELECT
  table_name,
  table_type,
  comment
FROM information_schema.tables
WHERE table_schema = '{schema}'
  {catalog_filter}
ORDER BY table_name
"""
        rows = self._executor.execute(sql)
        return [
            {
                "table_name": r["table_name"],
                "table_type": r.get("table_type", "TABLE"),
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
        schema = _safe_ident(schema)
        if catalog:
            catalog = _safe_ident(catalog)
            catalog_filter = f"AND table_catalog = '{catalog}'"
        else:
            catalog_filter = ""

        table_filter = ""
        if table_names:
            safe_names = [_safe_ident(t) for t in table_names]
            quoted = ", ".join(f"'{n}'" for n in safe_names)
            table_filter = f"AND table_name IN ({quoted})"

        sql = f"""
SELECT
  table_name,
  column_name,
  data_type,
  ordinal_position,
  is_nullable,
  comment
FROM information_schema.columns
WHERE table_schema = '{schema}'
  {catalog_filter}
  {table_filter}
ORDER BY table_name, ordinal_position
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
        # Primary path: derive distinct schemas from information_schema.tables.
        # Fallback path: SHOW SCHEMAS (for workspaces where information_schema
        # shape/availability varies by catalog or permissions).
        if catalog:
            catalog_filter = f"AND table_catalog = '{_safe_ident(catalog)}'"
        else:
            catalog_filter = ""
        sql = (
            f"SELECT DISTINCT table_schema AS schema_name "
            f"FROM information_schema.tables "
            f"WHERE table_schema IS NOT NULL "
            f"{catalog_filter} "
            f"ORDER BY table_schema"
        )
        names: list[str] = []
        try:
            rows = self._executor.execute(sql)
            names = self._extract_schema_names(rows)
        except METADATA_FALLBACK_ERRORS:
            logger.warning(
                "list_schemas: information_schema query failed; falling back to SHOW SCHEMAS",
                exc_info=True,
            )

        if names:
            return names

        logger.warning("list_schemas: falling back to SHOW SCHEMAS")
        fallback_sql = (
            f"SHOW SCHEMAS IN `{_safe_ident(catalog)}`"
            if catalog
            else "SHOW SCHEMAS"
        )
        fallback_rows = self._executor.execute(fallback_sql)
        return self._extract_schema_names(fallback_rows)

    @staticmethod
    def _extract_schema_names(rows: list[dict]) -> list[str]:
        names: list[str] = []
        for row in rows:
            raw = (
                row.get("schema_name")
                or row.get("databaseName")
                or row.get("namespace")
                or row.get("schema")
                or row.get("table_schema")
            )
            schema_name = str(raw or "").strip()
            if schema_name:
                names.append(schema_name)
        return sorted(set(names))

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
            # Step 1: sample row count
            count_sql = f"""
SELECT COUNT(*) AS row_count
FROM (
  SELECT * FROM {table_ref} TABLESAMPLE ({sample_pct} PERCENT)
  LIMIT {row_cap}
) _sample
"""
            count_rows = self._executor.execute(count_sql)
            sample_row_count = int((count_rows[0] or {}).get("row_count", 0)) if count_rows else 0

            # Step 2: one-pass null + distinct aggregation
            agg_exprs = []
            for col in columns:
                cname = _safe_ident(col["column_name"])
                agg_exprs.append(
                    f"SUM(CASE WHEN `{cname}` IS NULL THEN 1 ELSE 0 END) AS `null_{cname}`"
                )
                agg_exprs.append(f"approx_count_distinct(`{cname}`) AS `dist_{cname}`")

            agg_sql = f"""
SELECT {', '.join(agg_exprs)}
FROM (
  SELECT * FROM {table_ref} TABLESAMPLE ({sample_pct} PERCENT)
  LIMIT {row_cap}
) _sample
"""
            agg_rows = self._executor.execute(agg_sql)
            agg = agg_rows[0] if agg_rows else {}

            for col in columns:
                cname = col["column_name"]
                safe_cname = _safe_ident(cname)
                null_count = int(agg.get(f"null_{safe_cname}") or 0)
                approx_dist = int(agg.get(f"dist_{safe_cname}") or 0)
                null_pct = (null_count / sample_row_count) if sample_row_count > 0 else 0.0
                result[cname].update({
                    "null_count": null_count,
                    "null_pct": round(null_pct, 6),
                    "approx_distinct": approx_dist,
                    "sample_row_count": sample_row_count,
                })

        except METADATA_FALLBACK_ERRORS as exc:
            logger.exception("profile_table_columns: error sampling %s", table_ref)
            for col in columns:
                result[col["column_name"]]["sample_error"] = str(exc)[:500]
            return result

        # Step 3: per-column top values (per-column error isolation)
        for col in columns:
            cname = col["column_name"]
            dtype = col.get("data_type", "")
            approx_dist = result[cname].get("approx_distinct", 0)

            if _is_complex_type(dtype):
                continue
            if only_strings and not _is_string_type(dtype):
                continue
            if skip_id_like and _is_id_like(cname):
                continue

            try:
                safe_cname = _safe_ident(cname)
                if approx_dist > max_distinct:
                    value_sql = f"""
SELECT DISTINCT CAST(`{safe_cname}` AS STRING) AS val
FROM (
  SELECT * FROM {table_ref} TABLESAMPLE ({sample_pct} PERCENT)
  LIMIT {row_cap}
) _sample
WHERE `{safe_cname}` IS NOT NULL
LIMIT {per_col_limit}
"""
                else:
                    value_sql = f"""
SELECT CAST(`{safe_cname}` AS STRING) AS val, COUNT(*) AS cnt
FROM (
  SELECT * FROM {table_ref} TABLESAMPLE ({sample_pct} PERCENT)
  LIMIT {row_cap}
) _sample
WHERE `{safe_cname}` IS NOT NULL
GROUP BY `{safe_cname}`
ORDER BY cnt DESC
LIMIT {per_col_limit}
"""
                top_rows = self._executor.execute(value_sql)
                result[cname]["top_values"] = [str(r.get("val", "")) for r in top_rows]
            except METADATA_FALLBACK_ERRORS as exc:
                logger.warning(
                    "profile_table_columns: value sampling failed for %s.%s: %s",
                    table_ref, cname, exc,
                )
                result[cname]["sample_error"] = str(exc)[:500]

        return result
