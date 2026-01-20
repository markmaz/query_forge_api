from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

import pyarrow as pa

from app.adapters.databricks_sql_executor import DatabricksSQLExecutor
from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.ports.sql_executor import SQLExecutor

IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _safe_ident(s: str) -> str:
    if not IDENT_RE.fullmatch(s):
        raise ValueError(f"Unsafe identifier: {s!r}")
    return s


def _discover_default_catalog_schema(sql: DatabricksSQLExecutor) -> Tuple[str, str]:
    resp = sql.submit_statement(
        "SELECT current_catalog() AS catalog, current_schema() AS schema",
        result_format="ARROW_STREAM",
    )

    table: pa.Table = resp.get("table")
    if table is None or table.num_rows == 0:
        raise RuntimeError("No rows returned from current_catalog/current_schema")

    cat = table.column("catalog")[0].as_py()
    sch = table.column("schema")[0].as_py()
    if not cat or not sch:
        raise RuntimeError(f"Invalid current_catalog/current_schema: {(cat, sch)}")

    return str(cat), str(sch)


def _build_uc_metadata_sql(catalog: str, schema: str) -> str:
    catalog = _safe_ident(catalog)
    schema = _safe_ident(schema)

    return f"""
SELECT
  c.table_catalog  AS catalog_name,
  c.table_schema   AS schema_name,
  c.table_name,

  c.column_name,
  c.ordinal_position,
  c.data_type,
  c.is_nullable
FROM system.information_schema.columns c
WHERE c.table_catalog = '{catalog}'
  AND c.table_schema  = '{schema}'
ORDER BY c.table_name, c.ordinal_position
""".strip()


def _is_qe_from_variant(variant_code: Optional[str]) -> bool:
    if not variant_code:
        return False
    return "qe" in variant_code.lower()


def _split_base_and_variant(table_name: str, accepted_bases: Set[str]) -> Tuple[str, Optional[str]]:
    """
    Option A (current design):
      - model_table.name is the accepted base table name
      - a DBX table may be either:
          * exact match to a model base name (no variant)
          * base_variant where base is a model base name (variant present)
          * totally unmapped (treat whole name as base, no variant)

    This fixes cases like:
      mx_submitsline  -> base=mx_submitsline, variant=None  (NOT mx + submitsline)
      mx_submitsline_150 -> base=mx_submitsline, variant=150 (IF mx_submitsline exists in model_table.name)
    """
    t = (table_name or "").strip()
    if not t:
        return "", None

    if t in accepted_bases:
        return t, None

    # if no underscore, can't have variant by convention
    if "_" not in t:
        return t, None

    base, variant = t.rsplit("_", 1)
    base = base.strip()
    variant = (variant or "").strip() or None

    if base in accepted_bases:
        return base, variant

    # otherwise unmapped; do not split
    return t, None


@dataclass(frozen=True)
class SnapshotResult:
    ok: bool
    workspace_id: str
    catalog_name: str
    schema_name: str
    run_id: str
    ran_at_utc: str
    tables_seen: int
    columns_seen: int


class WorkspaceSnapshotService:
    """
    Snapshots UC metadata into:
      - workspace_table (per physical table, with base-name stored in table_name)
      - workspace_column (per physical table column)

    Mapping rule (Option A):
      - base table name MUST match model_table.name
      - workspace_table.model_table_id is nullable for unmapped tables
    """

    def __init__(self, *, sql: DatabricksSQLExecutor, mysql: Optional[SQLExecutor] = None):
        self._sql = sql
        self._mysql = mysql or MySQLSQLExecutor()

    def sync_snapshot(
        self,
        *,
        workspace_id: str,
        schema_name: str = "asset",
        catalog_name: Optional[str] = None,
    ) -> SnapshotResult:
        run_id = str(uuid.uuid4())
        now = datetime.utcnow()

        if catalog_name is None:
            default_cat, _default_schema = _discover_default_catalog_schema(self._sql)
            catalog_name = default_cat

        sql_text = _build_uc_metadata_sql(catalog=catalog_name, schema=schema_name)
        resp = self._sql.submit_statement(sql_text, result_format="ARROW_STREAM")

        table: pa.Table = resp.get("table")
        if table is None or table.num_rows == 0:
            return SnapshotResult(
                ok=True,
                workspace_id=workspace_id,
                catalog_name=catalog_name,
                schema_name=schema_name,
                run_id=run_id,
                ran_at_utc=now.isoformat(),
                tables_seen=0,
                columns_seen=0,
            )

        rows: List[Dict[str, Any]] = table.to_pylist()

        # Stage workspace tables and columns from snapshot
        ws_table_by_full: Dict[str, Dict[str, Any]] = {}
        col_stage: List[Dict[str, Any]] = []

        with self._mysql.transaction() as tx:
            # Ensure workspace exists
            tx.execute_write(
                "INSERT INTO workspace (id) VALUES (:id) ON DUPLICATE KEY UPDATE id=id",
                {"id": workspace_id},
            )

            # ✅ accepted bases come from model_table.name
            accepted_rows = tx.execute_query("SELECT name FROM model_table")
            accepted_bases: Set[str] = {str(r[0]) for r in accepted_rows}

            # We'll only use this for building model_id_by_base later
            base_names_seen: Set[str] = set()

            for r in rows:
                cat = str(r["catalog_name"])
                sch = str(r["schema_name"])
                physical_tbl = str(r["table_name"])  # physical DBX table name (may include variant)
                full = f"{cat}.{sch}.{physical_tbl}"

                base_name, variant_code = _split_base_and_variant(physical_tbl, accepted_bases)
                base_names_seen.add(base_name)

                is_qe = 1 if _is_qe_from_variant(variant_code) else 0

                if full not in ws_table_by_full:
                    ws_table_by_full[full] = {
                        "workspace_id": workspace_id,
                        "catalog_name": cat,
                        "schema_name": sch,
                        "table_name": base_name,
                        "full_name": full, 
                        "variant_code": variant_code,
                        "is_qe": is_qe,
                        "exists_in_dbx": 1,
                        "last_seen_at": now,
                    }

                col_stage.append(
                    {
                        "full_name": full,
                        "column_name": str(r["column_name"]),
                        "data_type": str(r["data_type"]),
                        "nullable": 1 if str(r["is_nullable"]).upper() == "YES" else 0,
                        "ordinal_position": int(r["ordinal_position"]),
                        "last_seen_at": now,
                    }
                )

            ws_tables = list(ws_table_by_full.values())

            # Map base name -> model_table.id (Option A)
            model_id_by_base: Dict[str, int] = {}
            if base_names_seen:
                names = sorted(base_names_seen)
                placeholders = ",".join([f":n{i}" for i in range(len(names))])
                params = {f"n{i}": name for i, name in enumerate(names)}
                model_rows = tx.execute_query_mappings(
                    f"""
                    SELECT id, name
                    FROM model_table
                    WHERE name IN ({placeholders})
                    """,
                    params,
                )
                model_id_by_base = {str(m["name"]): int(m["id"]) for m in model_rows}

            # Mark stale (this workspace+schema)
            tx.execute_write(
                """
                UPDATE workspace_table
                SET exists_in_dbx=0, updated_at=CURRENT_TIMESTAMP
                WHERE workspace_id=:ws
                  AND schema_name=:schema
                """,
                {"ws": workspace_id, "schema": schema_name},
            )

            tx.execute_write(
                """
                UPDATE workspace_column wc
                JOIN workspace_table wt ON wt.id = wc.workspace_table_id
                SET wc.exists_in_dbx=0, wc.updated_at=CURRENT_TIMESTAMP
                WHERE wt.workspace_id=:ws
                  AND wt.schema_name=:schema
                """,
                {"ws": workspace_id, "schema": schema_name},
            )

            # Upsert workspace_table (mapped OR unmapped)
            ws_payload: List[Dict[str, Any]] = []
            for t in ws_tables:
                base = t["table_name"]
                mid = model_id_by_base.get(base)  # may be None

                ws_payload.append(
                    {
                        "workspace_id": workspace_id,
                        "model_table_id": mid,  # ✅ nullable (unmapped)
                        "catalog_name": t["catalog_name"],
                        "schema_name": t["schema_name"],
                        "table_name": t["table_name"],  # base
                        "full_name": t["full_name"],    # physical full
                        "variant_code": t["variant_code"],
                        "is_qe": t["is_qe"],
                        "last_seen_at": now,
                    }
                )

            if ws_payload:
                tx.execute_write(
                    """
                    INSERT INTO workspace_table
                    (workspace_id, model_table_id, catalog_name, schema_name, table_name, full_name,
                     variant_code, is_qe, exists_in_dbx, last_seen_at, created_at)
                    VALUES
                    (:workspace_id, :model_table_id, :catalog_name, :schema_name, :table_name, :full_name,
                     :variant_code, :is_qe, 1, :last_seen_at, CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE
                     model_table_id=VALUES(model_table_id),
                     catalog_name=VALUES(catalog_name),
                     schema_name=VALUES(schema_name),
                     table_name=VALUES(table_name),
                     variant_code=VALUES(variant_code),
                     is_qe=VALUES(is_qe),
                     exists_in_dbx=1,
                     last_seen_at=VALUES(last_seen_at),
                     updated_at=CURRENT_TIMESTAMP
                    """,
                    ws_payload,
                )

            # Map full_name -> workspace_table_id (current only)
            id_rows = tx.execute_query_mappings(
                """
                SELECT id, full_name
                FROM workspace_table
                WHERE workspace_id=:ws
                  AND schema_name=:schema
                  AND exists_in_dbx=1
                """,
                {"ws": workspace_id, "schema": schema_name},
            )
            ws_table_id_by_full = {str(r["full_name"]): int(r["id"]) for r in id_rows}

            # Upsert workspace_column (all current tables)
            col_payload: List[Dict[str, Any]] = []
            for c in col_stage:
                wt_id = ws_table_id_by_full.get(c["full_name"])
                if not wt_id:
                    continue
                col_payload.append(
                    {
                        "workspace_table_id": wt_id,
                        "column_name": c["column_name"],
                        "data_type": c["data_type"],
                        "nullable": c["nullable"],
                        "ordinal_position": c["ordinal_position"],
                        "last_seen_at": now,
                    }
                )

            if col_payload:
                tx.execute_write(
                    """
                    INSERT INTO workspace_column
                    (workspace_table_id, column_name, data_type, nullable, ordinal_position,
                     exists_in_dbx, last_seen_at, created_at)
                    VALUES
                    (:workspace_table_id, :column_name, :data_type, :nullable, :ordinal_position,
                     1, :last_seen_at, CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE
                     data_type=VALUES(data_type),
                     nullable=VALUES(nullable),
                     ordinal_position=VALUES(ordinal_position),
                     exists_in_dbx=1,
                     last_seen_at=VALUES(last_seen_at),
                     updated_at=CURRENT_TIMESTAMP
                    """,
                    col_payload,
                )

        return SnapshotResult(
            ok=True,
            workspace_id=workspace_id,
            catalog_name=catalog_name,
            schema_name=schema_name,
            run_id=run_id,
            ran_at_utc=now.isoformat(),
            tables_seen=len(ws_table_by_full),
            columns_seen=len(col_stage),
        )
