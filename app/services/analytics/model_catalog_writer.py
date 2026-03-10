# app/services/analytics/model_catalog_writer.py
from __future__ import annotations

import logging
from typing import Any

from app.adapters.mysql_sql_executor import ForgeMetaSQL

logger = logging.getLogger(__name__)


def _chunk(xs: list, n: int = 500) -> list:
    return [xs[i:i + n] for i in range(0, len(xs), n)]


class ModelCatalogWriter:
    """Owns all MySQL upsert logic for model_table and model_column.

    Preserves description and semantic_* fields by default.
    Never touches the analytics datasource — writes only to the application DB.
    """

    def __init__(self, *, mysql: ForgeMetaSQL | None = None) -> None:
        self._mysql = mysql or ForgeMetaSQL()

    # ------------------------------------------------------------------
    # model_table
    # ------------------------------------------------------------------

    def upsert_tables(
        self,
        tables: list[dict],
        origin: str,
        overwrite_descriptions: bool = False,
    ) -> dict[str, Any]:
        """Upsert into model_table. Returns {tables_upserted, name_to_id}."""
        if not tables:
            return {"tables_upserted": 0, "name_to_id": {}}

        payload = [
            {
                "name": t["table_name"],
                "source_table_name": t.get("table_name"),
                "description": t.get("comment") or None,
                "origin": origin.upper(),
            }
            for t in tables
        ]

        desc_update = (
            "description = COALESCE(description, VALUES(description)),"
            if not overwrite_descriptions
            else "description = VALUES(description),"
        )

        with self._mysql.transaction() as tx:
            for batch in _chunk(payload, 500):
                tx.execute_write(
                    f"""
INSERT INTO model_table (name, source_table_name, description, origin, is_missing_in_source, created_at)
VALUES (:name, :source_table_name, :description, :origin, 0, CURRENT_TIMESTAMP)
ON DUPLICATE KEY UPDATE
  source_table_name    = VALUES(source_table_name),
  {desc_update}
  origin               = VALUES(origin),
  is_missing_in_source = 0,
  updated_at           = CURRENT_TIMESTAMP
""",
                    batch,
                )

            names = sorted({t["table_name"] for t in tables})
            name_to_id: dict[str, int] = {}
            for batch in _chunk(names, 500):
                placeholders = ", ".join(f":n{i}" for i in range(len(batch)))
                params = {f"n{i}": n for i, n in enumerate(batch)}
                rows = tx.execute_query_mappings(
                    f"SELECT id, name FROM model_table WHERE name IN ({placeholders})",
                    params,
                )
                for r in rows:
                    name_to_id[str(r["name"])] = int(r["id"])

        return {"tables_upserted": len(tables), "name_to_id": name_to_id}

    def mark_tables_missing(self, seen_names: set[str], origin: str) -> int:
        """Mark model_table rows with given origin as is_missing_in_source=1 if NOT in seen_names."""
        if not seen_names:
            return 0
        names = sorted(seen_names)
        total = 0
        with self._mysql.transaction() as tx:
            for batch in _chunk(names, 500):
                placeholders = ", ".join(f":n{i}" for i in range(len(batch)))
                params = {"origin": origin.upper(), **{f"n{i}": n for i, n in enumerate(batch)}}
                affected = tx.execute_write(
                    f"""
UPDATE model_table
SET is_missing_in_source = 1, updated_at = CURRENT_TIMESTAMP
WHERE origin = :origin
  AND is_missing_in_source = 0
  AND name NOT IN ({placeholders})
""",
                    params,
                )
                total += int(affected or 0)
        return total

    # ------------------------------------------------------------------
    # model_column
    # ------------------------------------------------------------------

    def upsert_columns(
        self,
        table_id_by_name: dict[str, int],
        columns: list[dict],
        origin: str,
        overwrite_descriptions: bool = False,
    ) -> dict[str, Any]:
        """Upsert into model_column. Returns {columns_upserted, cols_by_table_id}."""
        if not columns:
            return {"columns_upserted": 0, "cols_by_table_id": {}}

        payload = []
        cols_by_table_id: dict[int, set] = {}

        for col in columns:
            tid = table_id_by_name.get(col["table_name"])
            if tid is None:
                continue
            cn = col["column_name"]
            cols_by_table_id.setdefault(tid, set()).add(cn)

            nullable_val = col.get("is_nullable", True)
            nullable = 1 if bool(nullable_val) else 0

            payload.append({
                "model_table_id": tid,
                "column_name": cn,
                "data_type": col.get("data_type"),
                "ordinal_position": int(col.get("ordinal_position") or 0),
                "nullable": nullable,
                "description": col.get("comment") or None,
                "origin": origin.upper(),
            })

        if not payload:
            return {"columns_upserted": 0, "cols_by_table_id": cols_by_table_id}

        desc_update = (
            "description = COALESCE(description, VALUES(description)),"
            if not overwrite_descriptions
            else "description = VALUES(description),"
        )

        columns_upserted = 0
        with self._mysql.transaction() as tx:
            for batch in _chunk(payload, 2000):
                tx.execute_write(
                    f"""
INSERT INTO model_column
  (model_table_id, column_name, data_type, ordinal_position, nullable,
   description, is_active, origin, is_missing_in_source, created_at)
VALUES
  (:model_table_id, :column_name, :data_type, :ordinal_position, :nullable,
   :description, 1, :origin, 0, CURRENT_TIMESTAMP)
ON DUPLICATE KEY UPDATE
  data_type            = VALUES(data_type),
  ordinal_position     = VALUES(ordinal_position),
  nullable             = VALUES(nullable),
  {desc_update}
  is_active            = 1,
  origin               = VALUES(origin),
  is_missing_in_source = 0,
  updated_at           = CURRENT_TIMESTAMP
""",
                    batch,
                )
                columns_upserted += len(batch)

        return {"columns_upserted": columns_upserted, "cols_by_table_id": cols_by_table_id}

    def mark_columns_missing(self, cols_by_table_id: dict[int, set], origin: str) -> int:
        """Mark model_column rows as is_missing_in_source=1 if not in the seen set."""
        total = 0
        with self._mysql.transaction() as tx:
            for tid, colset in cols_by_table_id.items():
                cols_list = sorted(colset)
                if not cols_list:
                    continue
                placeholders = ", ".join(f":c{i}" for i in range(len(cols_list)))
                params = {
                    "tid": tid,
                    "origin": origin.upper(),
                    **{f"c{i}": cn for i, cn in enumerate(cols_list)},
                }
                affected = tx.execute_write(
                    f"""
UPDATE model_column
SET is_missing_in_source = 1, updated_at = CURRENT_TIMESTAMP
WHERE model_table_id = :tid
  AND origin = :origin
  AND is_missing_in_source = 0
  AND column_name NOT IN ({placeholders})
""",
                    params,
                )
                total += int(affected or 0)
        return total
