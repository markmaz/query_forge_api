from __future__ import annotations

import argparse
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

# Your existing executors (as provided)
from app.adapters.databricks_sql_executor import DatabricksForgeQueryPort
from app.adapters.mysql_sql_executor import ForgeMetaSQL

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ----------------------------
# Token provider for DatabricksForgeQueryPort
# ----------------------------
class StaticTokenProvider:
    """Minimal token provider compatible with DatabricksForgeQueryPort._resolve_token()."""

    def __init__(self, token: str):
        self.token = token


# ----------------------------
# Helpers / parsing
# ----------------------------
@dataclass(frozen=True)
class TableRef:
    catalog: str
    schema: str
    table: str

    @property
    def fq(self) -> str:
        return f"{self.catalog}.{self.schema}.{self.table}"


# Accept:
#   catalog.schema.table
#   schema.table
#   table
_TABLE_REF_3_RE = re.compile(r"^([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)$")
_TABLE_REF_2_RE = re.compile(r"^([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)$")
_TABLE_REF_1_RE = re.compile(r"^([A-Za-z0-9_]+)$")


def is_blank(s: Optional[str]) -> bool:
    return s is None or str(s).strip() == ""


def clamp_prompt(s: str, max_chars: int) -> str:
    s = s.strip()
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 50] + "\n...(truncated)...\n" + s[-50:]


# ----------------------------
# Databricks SQL helpers
# ----------------------------
def dbx_query_rows(dbx: DatabricksForgeQueryPort, sql: str, *, timeout_s: int = 600) -> List[Dict[str, Any]]:
    """
    Uses ARROW_STREAM so result rows come back as dicts via pyarrow.Table.to_pylist().
    """
    res = dbx.submit_statement(sql, wait=True, qf_timeout_s=timeout_s, qf_result_fmt="ARROW_STREAM")
    state = (res.get("status") or {}).get("state")
    if state != "SUCCEEDED":
        raise RuntimeError(f"Databricks statement failed. state={state} res={res}")
    return res.get("rows") or []


def sql_string_literal(s: str) -> str:
    """Single-quote escape for Databricks SQL."""
    return "'" + s.replace("\\", "\\\\").replace("'", "''") + "'"


def get_current_catalog(dbx: DatabricksForgeQueryPort) -> str:
    rows = dbx_query_rows(dbx, "SELECT current_catalog() AS catalog")
    if not rows or not rows[0].get("catalog"):
        raise RuntimeError("Could not determine current_catalog() from Databricks session.")
    return str(rows[0]["catalog"])


def dbx_ai_query(dbx: DatabricksForgeQueryPort, endpoint_or_model: str, prompt: str) -> str:
    """
    Calls Databricks ai_query() once and returns a string.
    """
    prompt = clamp_prompt(prompt, 7000)  # keep prompts sane
    sql = f"""
    SELECT
      ai_query(
        '{endpoint_or_model}',
        {sql_string_literal(prompt)}
      ) AS generated_text
    """
    rows = dbx_query_rows(dbx, sql, qf_timeout_s=1200)
    if not rows:
        return ""
    return (rows[0].get("generated_text") or "").strip()


def parse_source_table_name(
    source_table_name: str,
    *,
    default_catalog: str,
    default_schema: Optional[str],
) -> TableRef:
    """
    Accepts:
      - catalog.schema.table
      - schema.table (uses default_catalog)
      - table (uses default_catalog + default_schema)
    """
    s = (source_table_name or "").strip()

    m3 = _TABLE_REF_3_RE.match(s)
    if m3:
        return TableRef(catalog=m3.group(1), schema=m3.group(2), table=m3.group(3))

    m2 = _TABLE_REF_2_RE.match(s)
    if m2:
        return TableRef(catalog=default_catalog, schema=m2.group(1), table=m2.group(2))

    m1 = _TABLE_REF_1_RE.match(s)
    if m1:
        if is_blank(default_schema):
            raise ValueError(
                "source_table_name is only a table name, but default schema is not set. "
                "Provide --default-schema (or env DBX_DEFAULT_SCHEMA)."
            )
        return TableRef(catalog=default_catalog, schema=str(default_schema), table=m1.group(1))

    raise ValueError(
        "source_table_name must be one of: catalog.schema.table OR schema.table OR table. "
        f"Got: {source_table_name}"
    )


# ----------------------------
# MySQL helpers via your executor
# ----------------------------
def mysql_select(mysql: ForgeMetaSQL, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    res = mysql.submit_statement(sql, parameters=params or {})
    return res.get("rows") or []


def mysql_write(mysql: ForgeMetaSQL, sql: str, params: Optional[Dict[str, Any]] = None) -> int:
    res = mysql.submit_statement(sql, parameters=params or {})
    return int(res.get("rowcount") or 0)


# ----------------------------
# Unity Catalog metadata fetch
# ----------------------------
def fetch_uc_columns(dbx: DatabricksForgeQueryPort, tref: TableRef) -> List[Dict[str, Any]]:
    sql = f"""
    SELECT
      column_name,
      full_data_type,
      ordinal_position,
      is_nullable,
      comment
    FROM system.information_schema.columns
    WHERE table_catalog = {sql_string_literal(tref.catalog)}
      AND table_schema  = {sql_string_literal(tref.schema)}
      AND table_name    = {sql_string_literal(tref.table)}
    ORDER BY ordinal_position
    """
    return dbx_query_rows(dbx, sql)


# ----------------------------
# Prompt templates (tight + non-hallucinatory)
# ----------------------------
def make_table_prompt(tref: TableRef, columns: Sequence[Dict[str, Any]]) -> str:
    col_lines = []
    for c in columns[:200]:  # safety
        col_lines.append(f"- {c['column_name']} ({c.get('full_data_type')})")
    cols_block = "\n".join(col_lines)

    return f"""
You are generating documentation for a database table.
Write a concise business-friendly description (1-2 sentences max).
Do NOT speculate beyond column names/types. Do NOT invent facts.

Catalog: {tref.catalog}
Schema: {tref.schema}
Table: {tref.table}

Columns:
{cols_block}

Return only the description text.
""".strip()


def make_column_prompt(tref: TableRef, col: Dict[str, Any]) -> str:
    return f"""
You are generating documentation for a database column.
Write a concise business-friendly description (1 sentence).
Do NOT speculate about values. Do NOT invent facts. Prefer a generic, safe description.

Catalog: {tref.catalog}
Schema: {tref.schema}
Table: {tref.table}
Column: {col['column_name']}
Type: {col.get('full_data_type')}
Nullable: {col.get('is_nullable')}

Return only the description text.
""".strip()


# ----------------------------
# Sync logic
# ----------------------------
def sync_dictionary(
    *,
    dbx: DatabricksForgeQueryPort,
    mysql: ForgeMetaSQL,
    ai_model_or_endpoint: str,
    default_catalog: str,
    default_schema: Optional[str],
    overwrite: bool,
    only_table_ids: Optional[set[int]],
) -> None:
    # 1) read model_table rows
    model_tables = mysql_select(
        mysql,
        """
        SELECT id, name, source_table_name, description, origin, is_missing_in_source
        FROM model_table
        WHERE origin = 'DBX'
          AND source_table_name IS NOT NULL
          AND TRIM(source_table_name) <> ''
        ORDER BY id
        """,
    )

    if only_table_ids:
        model_tables = [t for t in model_tables if int(t["id"]) in only_table_ids]

    logger.info("Found %d model_table rows to sync", len(model_tables))
    logger.info("Default catalog: %s", default_catalog)
    if default_schema:
        logger.info("Default schema: %s", default_schema)

    for t in model_tables:
        model_table_id = int(t["id"])
        source_table_name = t.get("source_table_name")

        try:
            tref = parse_source_table_name(
                str(source_table_name),
                default_catalog=default_catalog,
                default_schema=default_schema,
            )
        except Exception as e:
            logger.error(
                "Skipping model_table_id=%s due to bad source_table_name=%s (%s)",
                model_table_id,
                source_table_name,
                e,
            )
            continue

        logger.info("Syncing model_table_id=%s -> %s", model_table_id, tref.fq)

        # 2) fetch UC columns (if fails, mark missing and continue)
        try:
            uc_cols = fetch_uc_columns(dbx, tref)
        except Exception as e:
            logger.exception("Failed fetching UC columns for %s: %s", tref.fq, e)
            mysql_write(mysql, "UPDATE model_table SET is_missing_in_source=1 WHERE id=:id", {"id": model_table_id})
            continue

        if not uc_cols:
            logger.warning("No columns found for %s. Marking missing.", tref.fq)
            mysql_write(mysql, "UPDATE model_table SET is_missing_in_source=1 WHERE id=:id", {"id": model_table_id})
            continue

        # mark table as present
        mysql_write(mysql, "UPDATE model_table SET is_missing_in_source=0 WHERE id=:id", {"id": model_table_id})

        # 3) generate table description (optional / only if blank unless overwrite)
        existing_table_desc = t.get("description")
        if overwrite or is_blank(existing_table_desc):
            prompt = make_table_prompt(tref, uc_cols)
            table_desc = dbx_ai_query(dbx, ai_model_or_endpoint, prompt)
            if table_desc:
                mysql_write(
                    mysql,
                    """
                    UPDATE model_table
                    SET description = :desc, updated_at = CURRENT_TIMESTAMP
                    WHERE id = :id
                    """,
                    {"id": model_table_id, "desc": table_desc},
                )

        # 4) sync columns: create/update; and missing flags
        existing_cols = mysql_select(
            mysql,
            """
            SELECT id, column_name, description
            FROM model_column
            WHERE model_table_id = :model_table_id
            """,
            {"model_table_id": model_table_id},
        )
        existing_by_name = {str(r["column_name"]).lower(): r for r in existing_cols}

        # mark all existing as missing, then clear for those found
        mysql_write(
            mysql,
            "UPDATE model_column SET is_missing_in_source=1 WHERE model_table_id=:model_table_id",
            {"model_table_id": model_table_id},
        )

        for c in uc_cols:
            col_name = str(c["column_name"])
            key = col_name.lower()
            data_type = c.get("full_data_type")
            ordinal = int(c.get("ordinal_position") or 0)
            nullable = 1 if str(c.get("is_nullable") or "").upper() == "YES" else 0

            existing = existing_by_name.get(key)
            existing_desc = existing.get("description") if existing else None

            # Decide if we should generate a description
            should_gen = overwrite or is_blank(existing_desc)

            gen_desc = None
            if should_gen:
                prompt = make_column_prompt(tref, c)
                gen_desc = dbx_ai_query(dbx, ai_model_or_endpoint, prompt)

            if existing:
                # Update metadata; clear missing flag; set description only if blank unless overwrite
                mysql_write(
                    mysql,
                    """
                    UPDATE model_column
                    SET
                      data_type = :data_type,
                      ordinal_position = :ordinal_position,
                      nullable = :nullable,
                      is_missing_in_source = 0,
                      origin = 'DBX',
                      updated_at = CURRENT_TIMESTAMP,
                      description = CASE
                        WHEN :overwrite = 1 THEN COALESCE(:desc, description)
                        WHEN description IS NULL OR TRIM(description) = '' THEN COALESCE(:desc, description)
                        ELSE description
                      END
                    WHERE model_table_id = :model_table_id
                      AND column_name = :column_name
                    """,
                    {
                        "model_table_id": model_table_id,
                        "column_name": col_name,
                        "data_type": data_type,
                        "ordinal_position": ordinal,
                        "nullable": nullable,
                        "desc": gen_desc,
                        "overwrite": 1 if overwrite else 0,
                    },
                )
            else:
                # Insert new column
                mysql_write(
                    mysql,
                    """
                    INSERT INTO model_column
                      (model_table_id, column_name, data_type, description, ordinal_position, nullable,
                       is_active, origin, is_missing_in_source, created_at, updated_at)
                    VALUES
                      (:model_table_id, :column_name, :data_type, :description, :ordinal_position, :nullable,
                       1, 'DBX', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    {
                        "model_table_id": model_table_id,
                        "column_name": col_name,
                        "data_type": data_type,
                        "description": gen_desc,
                        "ordinal_position": ordinal,
                        "nullable": nullable,
                    },
                )

        logger.info("Finished table %s", tref.fq)

    logger.info("Sync complete.")


# ----------------------------
# Entrypoint
# ----------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate AI table/column descriptions from UC and sync to MySQL model_table/model_column."
    )
    parser.add_argument("--warehouse-id", default=os.getenv("DATABRICKS_WAREHOUSE_ID"), help="Databricks SQL Warehouse ID.")
    parser.add_argument("--dbx-host", default=os.getenv("DATABRICKS_HOST"), help="Databricks workspace URL.")
    parser.add_argument("--dbx-token", default=os.getenv("DATABRICKS_TOKEN"), help="Databricks PAT (or workspace token).")
    parser.add_argument(
        "--ai-endpoint",
        default=os.getenv("DBX_AI_ENDPOINT"),
        required=False,
        help="Model serving endpoint name (used by ai_query()).",
    )

    # Defaults to help parse source_table_name when it's not fully-qualified
    parser.add_argument(
        "--default-catalog",
        default=os.getenv("DBX_DEFAULT_CATALOG"),
        help="Used when model_table.source_table_name is schema.table or table. If not provided, script uses current_catalog().",
    )
    parser.add_argument(
        "--default-schema",
        default=os.getenv("DBX_DEFAULT_SCHEMA"),
        help="Required when model_table.source_table_name is only table (1-part).",
    )

    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing MySQL descriptions.")
    parser.add_argument("--only-table-ids", default="", help="Comma-separated model_table ids to process (optional).")

    args = parser.parse_args()

    token = "dapi7b74b3db398467a1062109efcdf00b77-3"
    host = "https://adb-927164193773577.17.azuredatabricks.net"
    warehouse_id = "a312b7bb5c61fc3b"
    ai_endpoint = "databricks-claude-3-7-sonnet"

    if not args.warehouse_id:
        if not warehouse_id:
            raise SystemExit("Missing --warehouse-id (or env DATABRICKS_WAREHOUSE_ID).")
        args.warehouse_id = warehouse_id

    if not args.dbx_host:
        if not host:
            raise SystemExit("Missing --dbx-host (or env DATABRICKS_HOST).")
        args.dbx_host = host

    if not args.dbx_token:
        if not token:
            raise SystemExit("Missing --dbx-token (or env DATABRICKS_TOKEN).")
        args.dbx_token = token

    if not args.ai_endpoint:
        if not ai_endpoint:
            raise SystemExit("Missing --ai-endpoint (or env DBX_AI_ENDPOINT).")
        args.ai_endpoint = ai_endpoint

    only_ids: Optional[set[int]] = None
    if args.only_table_ids.strip():
        only_ids = {int(x.strip()) for x in args.only_table_ids.split(",") if x.strip()}

    # Instantiate executors
    mysql = ForgeMetaSQL()
    dbx = DatabricksForgeQueryPort(
        base_url=args.dbx_host,
        token_provider=StaticTokenProvider(args.dbx_token),
        default_warehouse_id=args.warehouse_id,
    )

    # Resolve default catalog: use arg/env if provided; otherwise detect from session
    default_catalog = args.default_catalog
    if is_blank(default_catalog):
        default_catalog = get_current_catalog(dbx)
        logger.info("Detected current catalog: %s", default_catalog)

    sync_dictionary(
        dbx=dbx,
        mysql=mysql,
        ai_model_or_endpoint=args.ai_endpoint,
        default_catalog=str(default_catalog),
        default_schema="edfi_wh",
        overwrite=args.overwrite,
        only_table_ids=only_ids,
    )


if __name__ == "__main__":
    main()