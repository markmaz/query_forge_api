from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor, SQLTransaction
from app.services.shared.jsonify import jsonify_rows


class DomainJoinService:
    def __init__(self, *, sql: Optional[SQLExecutor] = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

    def list_domain_joins(self, *, workspace_id: str, domain_id: int) -> List[Dict[str, Any]]:
        sql = """
            SELECT
                dtj.id,
                dtj.domain_id,
                dtj.from_workspace_table_id,
                dtj.to_workspace_table_id,
                dtj.join_type,
                dtj.join_spec_json,
                dtj.sort_order,
                dtj.is_active,
                dtj.created_at,
                dtj.updated_at
            FROM domain_table_join dtj
            JOIN domain d ON d.id = dtj.domain_id
            WHERE d.workspace_id = :ws
              AND dtj.domain_id = :did
              AND dtj.is_active = 1
            ORDER BY dtj.sort_order, dtj.created_at
        """
        rows = self._sql.execute_query_mappings(sql, {"ws": workspace_id, "did": int(domain_id)})
        return jsonify_rows([dict(r) for r in rows])

    def create_join(
        self,
        *,
        workspace_id: str,
        domain_id: int,
        from_workspace_table_id: int,
        to_workspace_table_id: int,
        join_type: str,
        join_spec: Dict[str, Any],
        sort_order: int = 0,
    ) -> Dict[str, Any]:
        self._validate_join_type(join_type)
        self._validate_join_spec(join_spec)
        if from_workspace_table_id == to_workspace_table_id:
            raise ServiceError("from_workspace_table_id must differ from to_workspace_table_id", status_code=400)
        self._validate_join_tables(join_spec, from_workspace_table_id, to_workspace_table_id)

        with self._sql.transaction() as tx:
            self._ensure_domain(tx, workspace_id, domain_id)
            self._ensure_tables_in_domain(tx, domain_id, from_workspace_table_id, to_workspace_table_id)
            self._validate_join_expr_columns(tx, join_spec, from_workspace_table_id, to_workspace_table_id)
            self._ensure_unique_to_table(tx, domain_id, to_workspace_table_id, exclude_id=None)

            existing_rows = tx.execute_query_mappings(
                """
                    SELECT id, is_active
                    FROM domain_table_join
                    WHERE domain_id = :did
                      AND from_workspace_table_id = :from_id
                      AND to_workspace_table_id = :to_id
                      AND sort_order = :sort_order
                    LIMIT 1
                    """,
                {
                    "did": int(domain_id),
                    "from_id": int(from_workspace_table_id),
                    "to_id": int(to_workspace_table_id),
                    "sort_order": int(sort_order),
                },
            )
            existing = existing_rows[0] if existing_rows else None

            if existing:
                tx.execute_write(
                    """
                        UPDATE domain_table_join
                        SET
                            join_type = :join_type,
                            join_spec_json = :join_spec,
                            sort_order = :sort_order,
                            is_active = 1
                        WHERE id = :join_id
                        """,
                    {
                        "join_type": join_type,
                        "join_spec": json.dumps(join_spec),
                        "sort_order": int(sort_order),
                        "join_id": existing["id"],
                    },
                )
                return {"ok": True, "id": str(existing["id"])}

            sql = """
                INSERT INTO domain_table_join
                    (domain_id, from_workspace_table_id, to_workspace_table_id, join_type, join_spec_json, sort_order, is_active)
                VALUES
                    (:did, :from_id, :to_id, :join_type, :join_spec, :sort_order, 1)
            """
            payload = {
                "did": int(domain_id),
                "from_id": int(from_workspace_table_id),
                "to_id": int(to_workspace_table_id),
                "join_type": join_type,
                "join_spec": json.dumps(join_spec),
                "sort_order": int(sort_order),
            }
            result = tx.execute_insert(sql, payload)
            join_id = None
            try:
                join_id = result.lastrowid
            except Exception:
                join_id = None

        return {"ok": True, "id": str(join_id) if join_id else None}

    def update_join(
        self,
        *,
        workspace_id: str,
        domain_id: int,
        join_id: str,
        from_workspace_table_id: int,
        to_workspace_table_id: int,
        join_type: str,
        join_spec: Dict[str, Any],
        sort_order: int = 0,
    ) -> Dict[str, Any]:
        self._validate_join_type(join_type)
        self._validate_join_spec(join_spec)
        if from_workspace_table_id == to_workspace_table_id:
            raise ServiceError("from_workspace_table_id must differ from to_workspace_table_id", status_code=400)
        self._validate_join_tables(join_spec, from_workspace_table_id, to_workspace_table_id)

        with self._sql.transaction() as tx:
            self._ensure_domain(tx, workspace_id, domain_id)
            self._ensure_join_exists(tx, domain_id, join_id)
            self._ensure_tables_in_domain(tx, domain_id, from_workspace_table_id, to_workspace_table_id)
            self._validate_join_expr_columns(tx, join_spec, from_workspace_table_id, to_workspace_table_id)
            self._ensure_unique_to_table(tx, domain_id, to_workspace_table_id, exclude_id=join_id)

            sql = """
                UPDATE domain_table_join
                SET
                    from_workspace_table_id = :from_id,
                    to_workspace_table_id = :to_id,
                    join_type = :join_type,
                    join_spec_json = :join_spec,
                    sort_order = :sort_order
                WHERE domain_id = :did
                  AND id = :join_id
            """
            tx.execute_write(
                sql,
                {
                    "from_id": int(from_workspace_table_id),
                    "to_id": int(to_workspace_table_id),
                    "join_type": join_type,
                    "join_spec": json.dumps(join_spec),
                    "sort_order": int(sort_order),
                    "did": int(domain_id),
                    "join_id": join_id,
                },
            )

        return {"ok": True}

    def delete_join(self, *, workspace_id: str, domain_id: int, join_id: str) -> Dict[str, Any]:
        with self._sql.transaction() as tx:
            self._ensure_domain(tx, workspace_id, domain_id)
            self._ensure_join_exists(tx, domain_id, join_id)
            sql = """
                UPDATE domain_table_join
                SET is_active = 0
                WHERE domain_id = :did
                  AND id = :join_id
            """
            tx.execute_write(sql, {"did": int(domain_id), "join_id": join_id})
        return {"ok": True}

    def set_primary_table(self, *, workspace_id: str, domain_id: int, workspace_table_id: int) -> List[Dict[str, Any]]:
        with self._sql.transaction() as tx:
            self._ensure_domain(tx, workspace_id, domain_id)
            exists_rows = tx.execute_query_mappings(
                """
                    SELECT 1
                    FROM domain_workspace_table
                    WHERE domain_id = :did
                      AND workspace_table_id = :wtid
                    LIMIT 1
                    """,
                {"did": int(domain_id), "wtid": int(workspace_table_id)},
            )
            exists = exists_rows[0] if exists_rows else None
            if not exists:
                raise ServiceError("Table is not assigned to this domain", status_code=400)

            tx.execute_write(
                "UPDATE domain_workspace_table SET is_primary = 0 WHERE domain_id = :did",
                {"did": int(domain_id)},
            )
            tx.execute_write(
                """
                    UPDATE domain_workspace_table
                    SET is_primary = 1
                    WHERE domain_id = :did
                      AND workspace_table_id = :wtid
                    """,
                {"did": int(domain_id), "wtid": int(workspace_table_id)},
            )

            tx.execute_write(
                """
                    UPDATE domain_table_join
                    SET is_active = 0
                    WHERE domain_id = :did
                      AND to_workspace_table_id = :wtid
                      AND is_active = 1
                    """,
                {"did": int(domain_id), "wtid": int(workspace_table_id)},
            )

            sql = """
                SELECT
                wt.id               AS workspace_table_id,
                d.model_table_id    AS model_table_id,
                mt.name             AS model_table_name,
                dwt.relation_kind   AS relation_kind,
                dwt.is_primary      AS is_primary,
                dwt.sort_order      AS sort_order,
                dwt.table_alias     AS table_alias,
                dwt.role            AS role,
                wt.catalog_name,
                wt.schema_name,
                wt.table_name,
                wt.full_name,
                wt.variant_code,
                wt.is_qe,
                wt.exists_in_dbx,
                wt.last_seen_at
                FROM domain_workspace_table dwt
                JOIN domain d
                ON d.id = dwt.domain_id
                JOIN workspace_table wt
                ON wt.id = dwt.workspace_table_id
                LEFT JOIN model_table mt
                ON mt.id = d.model_table_id
                WHERE d.workspace_id = :ws
                AND d.id = :did
                ORDER BY COALESCE(mt.name, ''), wt.full_name;
            """
            rows = tx.execute_query_mappings(sql, {"ws": workspace_id, "did": int(domain_id)})

        return jsonify_rows([dict(r) for r in rows])

    def _ensure_domain(self, tx: SQLTransaction, workspace_id: str, domain_id: int) -> None:
        rows = tx.execute_query_mappings(
            "SELECT id FROM domain WHERE id = :did AND workspace_id = :ws AND is_active = 1 LIMIT 1",
            {"did": int(domain_id), "ws": workspace_id},
        )
        row = rows[0] if rows else None
        if not row:
            raise ServiceError("Domain not found", status_code=404)

    def _ensure_tables_in_domain(self, tx: SQLTransaction, domain_id: int, from_id: int, to_id: int) -> None:
        sql = """
            SELECT workspace_table_id
            FROM domain_workspace_table
            WHERE domain_id = :did
              AND workspace_table_id IN (:from_id, :to_id)
        """
        rows = tx.execute_query_mappings(
            sql, {"did": int(domain_id), "from_id": int(from_id), "to_id": int(to_id)}
        )
        ids = {int(r["workspace_table_id"]) for r in rows}
        if int(from_id) not in ids or int(to_id) not in ids:
            raise ServiceError("Both tables must be assigned to the domain", status_code=400)

    def _ensure_unique_to_table(self, tx: SQLTransaction, domain_id: int, to_id: int, exclude_id: Optional[str]) -> None:
        sql = """
            SELECT id
            FROM domain_table_join
            WHERE domain_id = :did
              AND to_workspace_table_id = :to_id
              AND is_active = 1
        """
        rows = tx.execute_query_mappings(sql, {"did": int(domain_id), "to_id": int(to_id)})
        for r in rows:
            if exclude_id and str(r["id"]) == str(exclude_id):
                continue
            raise ServiceError("This table already has an active join", status_code=400)

    def _ensure_join_exists(self, tx: SQLTransaction, domain_id: int, join_id: str) -> None:
        rows = tx.execute_query_mappings(
            "SELECT id FROM domain_table_join WHERE domain_id = :did AND id = :join_id LIMIT 1",
            {"did": int(domain_id), "join_id": join_id},
        )
        row = rows[0] if rows else None
        if not row:
            raise ServiceError("Join not found", status_code=404)

    def _validate_join_type(self, join_type: str) -> None:
        if join_type not in {"LEFT", "INNER", "RIGHT"}:
            raise ServiceError("Invalid join_type", status_code=400)

    def _validate_join_spec(self, join_spec: Dict[str, Any]) -> None:
        if not isinstance(join_spec, dict):
            raise ServiceError("joinSpec must be an object", status_code=400)
        on_list = join_spec.get("on") or []
        if not isinstance(on_list, list) or len(on_list) == 0:
            raise ServiceError("joinSpec.on must be a non-empty array", status_code=400)
        for item in on_list:
            if not isinstance(item, dict):
                raise ServiceError("joinSpec.on items must be objects", status_code=400)
            op = item.get("op")
            if op and op != "=":
                raise ServiceError("joinSpec.on only supports '=' operator", status_code=400)
            left = item.get("left") or {}
            right = item.get("right") or {}
            self._validate_join_side(left, side_label="left")
            self._validate_join_side(right, side_label="right")

    def _validate_join_tables(self, join_spec: Dict[str, Any], from_id: int, to_id: int) -> None:
        for item in join_spec.get("on") or []:
            left = item.get("left") or {}
            right = item.get("right") or {}
            if left.get("workspaceTableId") is not None and int(left.get("workspaceTableId") or 0) != int(from_id):
                raise ServiceError("joinSpec.left.workspaceTableId must match fromWorkspaceTableId", status_code=400)
            if right.get("workspaceTableId") is not None and int(right.get("workspaceTableId") or 0) != int(to_id):
                raise ServiceError("joinSpec.right.workspaceTableId must match toWorkspaceTableId", status_code=400)

    def _validate_join_side(self, side: Dict[str, Any], *, side_label: str) -> None:
        if not isinstance(side, dict):
            raise ServiceError(f"joinSpec.{side_label} must be an object", status_code=400)
        has_expr = bool(side.get("expr"))
        col = side.get("columnName") or side.get("col")
        has_col = bool(col)
        if has_expr and has_col:
            raise ServiceError(f"joinSpec.{side_label} cannot include both expr and column", status_code=400)
        if not has_expr and not has_col:
            raise ServiceError(f"joinSpec.{side_label} must include expr or column", status_code=400)
        if has_expr and not isinstance(side.get("expr"), str):
            raise ServiceError(f"joinSpec.{side_label}.expr must be a string", status_code=400)
        if has_col and not isinstance(col, str):
            raise ServiceError(f"joinSpec.{side_label}.column must be a string", status_code=400)

    def _validate_join_expr_columns(self, tx: SQLTransaction, join_spec: Dict[str, Any], from_id: int, to_id: int) -> None:
        for item in join_spec.get("on") or []:
            left = item.get("left") or {}
            right = item.get("right") or {}
            self._validate_expr_side(tx, left, expected_scope="from", workspace_table_id=from_id, side_label="left")
            self._validate_expr_side(tx, right, expected_scope="to", workspace_table_id=to_id, side_label="right")

    def _validate_expr_side(
        self,
        tx: SQLTransaction,
        side: Dict[str, Any],
        *,
        expected_scope: str,
        workspace_table_id: int,
        side_label: str,
    ) -> None:
        expr = side.get("expr")
        if not expr:
            return
        scope, column_name, json_key = self._parse_json_expr(expr)
        if scope != expected_scope:
            raise ServiceError(
                f"joinSpec.{side_label}.expr must reference {{{expected_scope}}} columns",
                status_code=400,
            )
        if not self._column_exists(tx, workspace_table_id, column_name):
            raise ServiceError(
                f"joinSpec.{side_label}.expr column '{column_name}' not found on workspace table {workspace_table_id}",
                status_code=400,
            )
        if not json_key:
            raise ServiceError(f"joinSpec.{side_label}.expr must include a JSON key", status_code=400)

    def _parse_json_expr(self, expr: str) -> tuple[str, str, str]:
        pattern = r"^get_json_object\(\{(from|to)\}\.([A-Za-z0-9_]+),\s*'\$\.([A-Za-z0-9_]+)'\)$"
        match = re.match(pattern, expr)
        if not match:
            raise ServiceError(
                "joinSpec expr must match get_json_object({from|to}.<col>, '$.<key>')",
                status_code=400,
            )
        return match.group(1), match.group(2), match.group(3)

    def _column_exists(self, tx: SQLTransaction, workspace_table_id: int, column_name: str) -> bool:
        sql = """
            SELECT 1
            FROM workspace_column
            WHERE workspace_table_id = :wtid
              AND column_name = :col
            LIMIT 1
        """
        rows = tx.execute_query_mappings(sql, {"wtid": int(workspace_table_id), "col": column_name})
        return bool(rows)
