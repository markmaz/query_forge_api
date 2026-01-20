from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.ports.sql_executor import SQLExecutor


class ModelWriteService:
    def __init__(self, *, sql: SQLExecutor | None = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

    def upsert_dictionary(
        self,
        *,
        user_name: str,  # kept for future auditing
        rows: List[Dict[str, str]],
        full_replace: bool = False,
    ) -> Dict[str, int]:
        inserted_tables = 0
        inserted_columns = 0
        updated_columns = 0
        deactivated_columns = 0

        table_names = sorted(
            {
                (r.get("table_name") or "").strip()
                for r in rows
                if (r.get("table_name") or "").strip()
            }
        )
        table_names = [t for t in table_names if t]
        if not table_names:
            return dict(
                inserted_tables=0,
                inserted_columns=0,
                updated_columns=0,
                deactivated_columns=0,
            )

        with self._sql.transaction() as tx:
            # Upsert model_table
            payload_tables = [{"name": t, "description": None} for t in table_names]
            tx.execute_write(
                """
                    INSERT INTO model_table (name, description, created_at)
                    VALUES (:name, :description, CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE
                    updated_at=CURRENT_TIMESTAMP
                    """,
                payload_tables,
            )

            # Map table name -> id (✅ expanding bind)
            placeholders = ",".join([f":n{i}" for i in range(len(table_names))])
            result = tx.execute_query_mappings(
                f"""
                SELECT id, name
                FROM model_table
                WHERE name IN ({placeholders})
                """,
                {f"n{i}": name for i, name in enumerate(table_names)},
            )
            table_id_by_name = {str(r["name"]): int(r["id"]) for r in result}

            tids = list(table_id_by_name.values())
            if not tids:
                return dict(
                    inserted_tables=inserted_tables,
                    inserted_columns=0,
                    updated_columns=0,
                    deactivated_columns=0,
                )

            # Prefetch existing columns (✅ expanding bind)
            existing_keys: Set[Tuple[int, str]] = set()
            tid_placeholders = ",".join([f":t{i}" for i in range(len(tids))])
            result = tx.execute_query_mappings(
                f"""
                SELECT model_table_id, column_name
                FROM model_column
                WHERE model_table_id IN ({tid_placeholders})
                """,
                {f"t{i}": tid for i, tid in enumerate(tids)},
            )
            for r in result:
                existing_keys.add((int(r["model_table_id"]), str(r["column_name"]).lower()))

            payload_cols: List[Dict[str, Any]] = []
            seen: Set[Tuple[int, str]] = set()

            for r in rows:
                tname = (r.get("table_name") or "").strip()
                cname = (r.get("column_name") or "").strip()
                if not tname or not cname:
                    continue

                tid = table_id_by_name.get(tname)
                if not tid:
                    continue

                key = (tid, cname.lower())
                if key in seen:
                    continue
                seen.add(key)

                if key in existing_keys:
                    updated_columns += 1
                else:
                    inserted_columns += 1

                payload_cols.append(
                    {
                        "model_table_id": tid,
                        "column_name": cname,
                        "data_type": (r.get("data_type") or None),
                        "description": (r.get("description") or None),
                    }
                )

                if payload_cols:
                    tx.execute_write(
                        """
                            INSERT INTO model_column
                            (model_table_id, column_name, data_type, description, is_active, origin, is_missing_in_source, created_at)
                            VALUES
                            (:model_table_id, :column_name, :data_type, :description, 1, 'DICT', 1, CURRENT_TIMESTAMP)
                            ON DUPLICATE KEY UPDATE
                            description = VALUES(description),
                            is_active = 1,

                            -- critical: if row already exists from DBX import, keep it NOT missing
                            is_missing_in_source = CASE
                                WHEN origin = 'DBX' THEN 0
                                ELSE 1
                            END,

                            -- preserve DBX as origin if it is DBX; otherwise keep DICT
                            origin = CASE
                                WHEN origin = 'DBX' THEN 'DBX'
                                ELSE 'DICT'
                            END,

                            updated_at = CURRENT_TIMESTAMP
                """,
                        payload_cols,
                    )

            if full_replace:
                cols_by_table: Dict[int, Set[str]] = {}
                for r in rows:
                    tname = (r.get("table_name") or "").strip()
                    cname = (r.get("column_name") or "").strip()
                    tid = table_id_by_name.get(tname) if tname else None
                    if tid and cname:
                        cols_by_table.setdefault(tid, set()).add(cname)

                # Deactivate anything not present in the upload per table
                for tid, cols in cols_by_table.items():
                    # ✅ guard: NOT IN () is invalid SQL
                    if not cols:
                        continue

                    cols_sorted = sorted(cols)
                    placeholders = ",".join([f":c{i}" for i in range(len(cols_sorted))])
                    params = {"tid": tid, **{f"c{i}": col for i, col in enumerate(cols_sorted)}}
                    res = tx.execute_write(
                        f"""
                        UPDATE model_column
                        SET is_active=0, updated_at=CURRENT_TIMESTAMP
                        WHERE model_table_id = :tid
                        AND is_active = 1
                        AND column_name NOT IN ({placeholders})
                        """,
                        params,
                    )
                    deactivated_columns += int(res or 0)

        return dict(
            inserted_tables=inserted_tables,
            inserted_columns=inserted_columns,
            updated_columns=updated_columns,
            deactivated_columns=deactivated_columns,
        )
    
