from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

import pyarrow as pa

from app.adapters.databricks_sql_executor import DatabricksForgeQueryPort
from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort

IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _qf_safe_ident(s: str) -> str:
    if not IDENT_RE.fullmatch(s):
        raise ValueError(f"Unsafe identifier: {s!r}")
    return s


def _discover_default_catalog_schema(sql: DatabricksForgeQueryPort) -> Tuple[str, str]:
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


def _build_uc_metadata_sql(catalog: str, schema: str) -> str:
    catalog = _qf_safe_ident(catalog)
    schema = _qf_safe_ident(schema)

    return f"""
SELECT
  c.table_catalog  AS qf_catalog_name,
  c.table_schema   AS qf_schema_name,
  c.qf_table_name,
  c.column_name,
  c.qf_ordinal_position,
  c.data_type,
  c.is_nullable
FROM system.information_schema.columns c
WHERE c.table_catalog = '{catalog}'
  AND c.table_schema  = '{schema}'
ORDER BY c.qf_table_name, c.qf_ordinal_position
""".strip()


def _is_qe_from_variant(qf_variant_code: Optional[str]) -> bool:
    return bool(qf_variant_code and "qe" in qf_variant_code.lower())


def _split_base_and_variant(qf_table_name: str, accepted_bases: Set[str]) -> Tuple[str, Optional[str]]:
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


@dataclass(frozen=True)
class SnapshotResult:
    ok: bool
    workspace_id: str
    qf_catalog_name: str
    qf_schema_name: str
    run_id: str
    ran_at_utc: str
    tables_seen: int
    columns_seen: int


@dataclass(frozen=True)
class _TableStage:
    full_name: str
    qf_catalog_name: str
    qf_schema_name: str
    qf_table_name: str
    qf_variant_code: Optional[str]
    is_qe: int


@dataclass(frozen=True)
class _ColumnStage:
    full_name: str
    column_name: str
    data_type: str
    nullable: int
    qf_ordinal_position: int


class WorkspaceSnapshotService:
    """
    Snapshots UC metadata into:
      - workspace_table (per physical table)
      - workspace_column (per physical table column)

    Mapping rule:
      - model_table.name represents accepted base table names
      - workspace_table.model_table_id remains nullable for unmapped tables
    """

    def __init__(self, *, sql: DatabricksForgeQueryPort, mysql: Optional[ForgeQueryPort] = None):
        self._sql = sql
        self._mysql = mysql or ForgeMetaSQL()

    def sync_snapshot(
        self,
        *,
        workspace_id: str,
        qf_schema_name: str = "asset",
        qf_catalog_name: Optional[str] = None,
    ) -> SnapshotResult:
        run_id = str(uuid.uuid4())
        now = datetime.utcnow()

        if qf_catalog_name is None:
            qf_catalog_name, _ = _discover_default_catalog_schema(self._sql)

        sql_text = _build_uc_metadata_sql(catalog=qf_catalog_name, schema=qf_schema_name)
        response = self._sql.submit_statement(sql_text, qf_result_fmt="ARROW_STREAM")

        table: pa.Table = response.get("table")
        if table is None or table.num_rows == 0:
            return SnapshotResult(
                ok=True,
                workspace_id=workspace_id,
                qf_catalog_name=qf_catalog_name,
                qf_schema_name=qf_schema_name,
                run_id=run_id,
                ran_at_utc=now.isoformat(),
                tables_seen=0,
                columns_seen=0,
            )

        snapshot_rows: List[Dict[str, Any]] = table.to_pylist()

        with self._mysql.transaction() as tx:
            tx.execute_write(
                "INSERT INTO workspace (id) VALUES (:id) ON DUPLICATE KEY UPDATE id=id",
                {"id": workspace_id},
            )

            accepted_rows = tx.execute_query("SELECT name FROM model_table")
            accepted_bases = {str(row[0]) for row in accepted_rows}

            staged_tables, staged_columns, seen_bases = self._stage_rows(snapshot_rows, accepted_bases)
            model_id_by_base = self._resolve_model_ids(tx, seen_bases)

            self._mark_stale(tx, workspace_id=workspace_id, qf_schema_name=qf_schema_name)
            self._upsert_tables(
                tx,
                workspace_id=workspace_id,
                now=now,
                staged_tables=staged_tables,
                model_id_by_base=model_id_by_base,
            )

            table_id_by_full_name = self._load_current_workspace_table_ids(
                tx,
                workspace_id=workspace_id,
                qf_schema_name=qf_schema_name,
            )
            self._upsert_columns(
                tx,
                now=now,
                staged_columns=staged_columns,
                table_id_by_full_name=table_id_by_full_name,
            )

        return SnapshotResult(
            ok=True,
            workspace_id=workspace_id,
            qf_catalog_name=qf_catalog_name,
            qf_schema_name=qf_schema_name,
            run_id=run_id,
            ran_at_utc=now.isoformat(),
            tables_seen=len(staged_tables),
            columns_seen=len(staged_columns),
        )

    def _stage_rows(
        self,
        rows: List[Dict[str, Any]],
        accepted_bases: Set[str],
    ) -> Tuple[List[_TableStage], List[_ColumnStage], Set[str]]:
        table_by_full: Dict[str, _TableStage] = {}
        columns: List[_ColumnStage] = []
        seen_bases: Set[str] = set()

        for row in rows:
            qf_catalog_name = str(row["qf_catalog_name"])
            qf_schema_name = str(row["qf_schema_name"])
            physical_table = str(row["qf_table_name"])
            full_name = f"{qf_catalog_name}.{qf_schema_name}.{physical_table}"

            base_name, qf_variant_code = _split_base_and_variant(physical_table, accepted_bases)
            seen_bases.add(base_name)

            table_by_full.setdefault(
                full_name,
                _TableStage(
                    full_name=full_name,
                    qf_catalog_name=qf_catalog_name,
                    qf_schema_name=qf_schema_name,
                    qf_table_name=base_name,
                    qf_variant_code=qf_variant_code,
                    is_qe=1 if _is_qe_from_variant(qf_variant_code) else 0,
                ),
            )

            columns.append(
                _ColumnStage(
                    full_name=full_name,
                    column_name=str(row["column_name"]),
                    data_type=str(row["data_type"]),
                    nullable=1 if str(row["is_nullable"]).upper() == "YES" else 0,
                    qf_ordinal_position=int(row["qf_ordinal_position"]),
                )
            )

        return list(table_by_full.values()), columns, seen_bases

    def _resolve_model_ids(self, tx, base_names: Set[str]) -> Dict[str, int]:
        if not base_names:
            return {}

        names = sorted(base_names)
        placeholders = ",".join(f":n{i}" for i in range(len(names)))
        params = {f"n{i}": name for i, name in enumerate(names)}

        rows = tx.execute_query_mappings(
            f"""
            SELECT id, name
            FROM model_table
            WHERE name IN ({placeholders})
            """,
            params,
        )
        return {str(row["name"]): int(row["id"]) for row in rows}

    def _mark_stale(self, tx, *, workspace_id: str, qf_schema_name: str) -> None:
        tx.execute_write(
            """
            UPDATE workspace_table
            SET qf_exists_in_dbx=0, updated_at=CURRENT_TIMESTAMP
            WHERE workspace_id=:ws
              AND qf_schema_name=:schema
            """,
            {"ws": workspace_id, "schema": qf_schema_name},
        )
        tx.execute_write(
            """
            UPDATE workspace_column wc
            JOIN workspace_table wt ON wt.id = wc.workspace_table_id
            SET wc.qf_exists_in_dbx=0, wc.updated_at=CURRENT_TIMESTAMP
            WHERE wt.workspace_id=:ws
              AND wt.qf_schema_name=:schema
            """,
            {"ws": workspace_id, "schema": qf_schema_name},
        )

    def _upsert_tables(
        self,
        tx,
        *,
        workspace_id: str,
        now: datetime,
        staged_tables: List[_TableStage],
        model_id_by_base: Dict[str, int],
    ) -> None:
        if not staged_tables:
            return

        payload = [
            {
                "workspace_id": workspace_id,
                "model_table_id": model_id_by_base.get(stage.qf_table_name),
                "qf_catalog_name": stage.qf_catalog_name,
                "qf_schema_name": stage.qf_schema_name,
                "qf_table_name": stage.qf_table_name,
                "full_name": stage.full_name,
                "qf_variant_code": stage.qf_variant_code,
                "is_qe": stage.is_qe,
                "qf_last_seen_at": now,
            }
            for stage in staged_tables
        ]

        tx.execute_write(
            """
            INSERT INTO workspace_table
            (workspace_id, model_table_id, qf_catalog_name, qf_schema_name, qf_table_name, full_name,
             qf_variant_code, is_qe, qf_exists_in_dbx, qf_last_seen_at, created_at)
            VALUES
            (:workspace_id, :model_table_id, :qf_catalog_name, :qf_schema_name, :qf_table_name, :full_name,
             :qf_variant_code, :is_qe, 1, :qf_last_seen_at, CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE
             model_table_id=VALUES(model_table_id),
             qf_catalog_name=VALUES(qf_catalog_name),
             qf_schema_name=VALUES(qf_schema_name),
             qf_table_name=VALUES(qf_table_name),
             qf_variant_code=VALUES(qf_variant_code),
             is_qe=VALUES(is_qe),
             qf_exists_in_dbx=1,
             qf_last_seen_at=VALUES(qf_last_seen_at),
             updated_at=CURRENT_TIMESTAMP
            """,
            payload,
        )

    def _load_current_workspace_table_ids(self, tx, *, workspace_id: str, qf_schema_name: str) -> Dict[str, int]:
        rows = tx.execute_query_mappings(
            """
            SELECT id, full_name
            FROM workspace_table
            WHERE workspace_id=:ws
              AND qf_schema_name=:schema
              AND qf_exists_in_dbx=1
            """,
            {"ws": workspace_id, "schema": qf_schema_name},
        )
        return {str(row["full_name"]): int(row["id"]) for row in rows}

    def _upsert_columns(
        self,
        tx,
        *,
        now: datetime,
        staged_columns: List[_ColumnStage],
        table_id_by_full_name: Dict[str, int],
    ) -> None:
        payload: List[Dict[str, Any]] = []
        for column in staged_columns:
            table_id = table_id_by_full_name.get(column.full_name)
            if not table_id:
                continue
            payload.append(
                {
                    "workspace_table_id": table_id,
                    "column_name": column.column_name,
                    "data_type": column.data_type,
                    "nullable": column.nullable,
                    "qf_ordinal_position": column.qf_ordinal_position,
                    "qf_last_seen_at": now,
                }
            )

        if not payload:
            return

        tx.execute_write(
            """
            INSERT INTO workspace_column
            (workspace_table_id, column_name, data_type, nullable, qf_ordinal_position,
             qf_exists_in_dbx, qf_last_seen_at, created_at)
            VALUES
            (:workspace_table_id, :column_name, :data_type, :nullable, :qf_ordinal_position,
             1, :qf_last_seen_at, CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE
             data_type=VALUES(data_type),
             nullable=VALUES(nullable),
             qf_ordinal_position=VALUES(qf_ordinal_position),
             qf_exists_in_dbx=1,
             qf_last_seen_at=VALUES(qf_last_seen_at),
             updated_at=CURRENT_TIMESTAMP
            """,
            payload,
        )
