from __future__ import annotations

import re
from typing import Optional, Set, Tuple

import pyarrow as pa

from app.ports.sql_executor import ForgeQueryPort

IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")


def qf_safe_ident(value: str) -> str:
    if not IDENT_RE.fullmatch(value):
        raise ValueError(f"Unsafe identifier: {value!r}")
    return value


def discover_default_catalog_schema(sql: ForgeQueryPort) -> Tuple[str, str]:
    response = sql.submit_statement(
        "SELECT current_catalog() AS catalog, current_schema() AS schema",
        qf_result_fmt="ARROW_STREAM",
    )
    table: pa.Table = response.get("table")
    if table is None or table.num_rows == 0:
        raise RuntimeError("No rows returned from current_catalog/current_schema")

    catalog = table.column("catalog")[0].as_py()
    schema = table.column("schema")[0].as_py()
    if not catalog or not schema:
        raise RuntimeError(f"Invalid current_catalog/current_schema: {(catalog, schema)}")
    return str(catalog), str(schema)


def build_uc_metadata_sql(catalog: str, schema: str) -> str:
    catalog = qf_safe_ident(catalog)
    schema = qf_safe_ident(schema)

    return f"""
SELECT
  c.table_catalog  AS qf_catalog_name,
  c.table_schema   AS qf_schema_name,
  c.table_name     AS qf_table_name,
  c.column_name,
  c.ordinal_position AS qf_ordinal_position,
  c.data_type,
  c.is_nullable
FROM system.information_schema.columns c
WHERE c.table_catalog = '{catalog}'
  AND c.table_schema  = '{schema}'
ORDER BY c.table_name, c.ordinal_position
""".strip()


def is_qe_from_variant(qf_variant_code: Optional[str]) -> bool:
    return bool(qf_variant_code and "qe" in qf_variant_code.lower())


def split_base_and_variant(qf_table_name: str, accepted_bases: Set[str]) -> Tuple[str, Optional[str]]:
    text = (qf_table_name or "").strip()
    if not text:
        return "", None

    if text in accepted_bases:
        return text, None

    if "_" not in text:
        return text, None

    base, maybe_variant = text.rsplit("_", 1)
    base = base.strip()
    variant = (maybe_variant or "").strip() or None
    if base in accepted_bases:
        return base, variant
    return text, None
