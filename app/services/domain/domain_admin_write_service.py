from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor
from app.services.shared.jsonify import jsonify_dict


class DomainAdminWriteService:
    def __init__(self, *, sql: Optional[SQLExecutor] = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

    # ---------- permission helpers (unchanged) ----------
    def _can_edit_any(self, *, workspace_id: str, user_id: str) -> bool:
        sql_any_domain_exists = """
            SELECT 1
            FROM domain d
            WHERE d.workspace_id=:ws
            LIMIT 1
            """
        sql_has_any_edit = """
            SELECT 1
            FROM user_domain_mapping udm
            JOIN domain d ON d.id = udm.domain_id
            WHERE d.workspace_id=:ws
            AND d.is_active=1
            AND udm.user_id=:uid
            AND udm.can_edit=1
            LIMIT 1
            """
        any_domain = self._sql.execute_query(sql_any_domain_exists, {"ws": workspace_id})
        if not any_domain:
            return True
        row = self._sql.execute_query(sql_has_any_edit, {"ws": workspace_id, "uid": user_id})
        return bool(row)

    def _assert_can_edit_any(self, *, workspace_id: str, user_id: str) -> None:
        if not self._can_edit_any(workspace_id=workspace_id, user_id=user_id):
            raise ServiceError("You do not have permission to create domains.", status_code=403)

    def _assert_can_edit_domain(self, *, workspace_id: str, user_id: str, domain_id: int) -> None:
        sql = """
            SELECT 1
            FROM user_domain_mapping udm
            JOIN domain d ON d.id = udm.domain_id
            WHERE d.workspace_id=:ws
            AND d.id=:did
            AND d.is_active=1
            AND udm.user_id=:uid
            AND udm.can_edit=1
            LIMIT 1
"""
        row = self._sql.execute_query(sql, {"ws": workspace_id, "did": int(domain_id), "uid": user_id})
        if not row:
            raise ServiceError("You do not have edit permission for this domain.", status_code=403)

    # ---------- CRUD ----------

    def create_domain(
        self,
        *,
        workspace_id: str,
        user_id: str,
        name: str,
        kind: Optional[str] = None,
        description: Optional[str] = None,
        model_table_id: Optional[int] = None,  # ✅ NEW
        column_name_policy: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._assert_can_edit_any(workspace_id=workspace_id, user_id=user_id)

        name = (name or "").strip()
        if not name:
            raise ServiceError("name is required", status_code=400)

        kind = (kind or "").strip() or None
        description = (description or "").strip() or None
        mtid = int(model_table_id) if model_table_id is not None else None
        policy = (column_name_policy or "").strip().upper() or None
        if policy and policy not in {"DEDUP_PRIMARY_FIRST", "SHOW_ALL_QUALIFIED"}:
            raise ServiceError("Invalid column_name_policy", status_code=400)

        with self._sql.transaction() as tx:
            tx.execute_write(
                """
                INSERT INTO workspace (id, display_name)
                VALUES (:id, :display_name)
                ON DUPLICATE KEY UPDATE id=id
                """,
                {"id": workspace_id, "display_name": None},
            )

            res = tx.execute_insert(
                """
                    INSERT INTO domain (
                        workspace_id, name, kind, description, model_table_id,
                        column_name_policy, is_active, created_at
                    )
                    VALUES (:ws, :name, :kind, :desc, :mtid, :policy, 1, CURRENT_TIMESTAMP)
                    """,
                {
                    "ws": workspace_id,
                    "name": name,
                    "kind": kind,
                    "desc": description,
                    "mtid": mtid,
                    "policy": policy,
                },
            )
            domain_id = int(res.lastrowid or 0)

            tx.execute_write(
                """
                    INSERT INTO user_domain_mapping (user_id, domain_id, can_read, can_edit, created_at)
                    VALUES (:uid, :did, 1, 1, CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE can_read=1, can_edit=1
                    """,
                {"uid": user_id, "did": domain_id},
            )

            rows = tx.execute_query_mappings(
                """
                    SELECT
                    d.id, d.name, d.kind, d.description, d.model_table_id, d.column_name_policy,
                    mt.name AS model_table_name,
                    d.is_active, d.created_at, d.updated_at
                    FROM domain d
                    LEFT JOIN model_table mt ON mt.id = d.model_table_id
                    WHERE d.workspace_id=:ws AND d.id=:did
                    """,
                {"ws": workspace_id, "did": domain_id},
            )
            row = rows[0] if rows else None

        return jsonify_dict(dict(row)) if row else {
            "id": domain_id,
            "name": name,
            "kind": kind,
            "description": description,
            "modelTableId": mtid,
            "modelTableName": None,
        }

    def patch_domain(
        self,
        *,
        workspace_id: str,
        user_id: str,
        domain_id: int,
        name: Optional[str] = None,
        kind: Optional[str] = None,
        description: Optional[str] = None,
        is_active: Optional[bool] = None,
        model_table_id: Optional[int] = None,  # ✅ NEW
        column_name_policy: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._assert_can_edit_domain(workspace_id=workspace_id, user_id=user_id, domain_id=domain_id)

        updates: Dict[str, Any] = {"ws": workspace_id, "did": int(domain_id)}
        sets: List[str] = []

        if name is not None:
            n = name.strip()
            if not n:
                raise ServiceError("name cannot be empty", status_code=400)
            updates["name"] = n
            sets.append("name=:name")

        if kind is not None:
            updates["kind"] = kind.strip() or None
            sets.append("kind=:kind")

        if description is not None:
            updates["description"] = description.strip() or None
            sets.append("description=:description")

        if is_active is not None:
            updates["is_active"] = 1 if is_active else 0
            sets.append("is_active=:is_active")

        if model_table_id is not None:
            updates["model_table_id"] = int(model_table_id)
            sets.append("model_table_id=:model_table_id")

        if column_name_policy is not None:
            policy = column_name_policy.strip().upper()
            if policy not in {"DEDUP_PRIMARY_FIRST", "SHOW_ALL_QUALIFIED"}:
                raise ServiceError("Invalid column_name_policy", status_code=400)
            updates["column_name_policy"] = policy
            sets.append("column_name_policy=:column_name_policy")

        if not sets:
            raise ServiceError("No fields to update", status_code=400)

        with self._sql.transaction() as tx:
            tx.execute_write(
                f"""
                    UPDATE domain
                    SET {", ".join(sets)}, updated_at=CURRENT_TIMESTAMP
                    WHERE workspace_id=:ws AND id=:did
                    """,
                updates,
            )

            rows = tx.execute_query_mappings(
                """
                    SELECT
                    d.id, d.name, d.kind, d.description, d.model_table_id, d.column_name_policy,
                    mt.name AS model_table_name,
                    d.is_active, d.created_at, d.updated_at
                    FROM domain d
                    LEFT JOIN model_table mt ON mt.id = d.model_table_id
                    WHERE d.workspace_id=:ws AND d.id=:did
                    """,
                {"ws": workspace_id, "did": int(domain_id)},
            )
            row = rows[0] if rows else None

        if not row:
            raise ServiceError("Domain not found", status_code=404)

        return jsonify_dict(dict(row))

    def delete_domain(self, *, workspace_id: str, user_id: str, domain_id: int) -> Dict[str, Any]:
        self._assert_can_edit_domain(workspace_id=workspace_id, user_id=user_id, domain_id=domain_id)

        with self._sql.transaction() as tx:
            res = tx.execute_write(
                "DELETE FROM domain WHERE workspace_id=:ws AND id=:did",
                {"ws": workspace_id, "did": int(domain_id)},
            )
            if res == 0:
                raise ServiceError("Domain not found", status_code=404)

        return {"ok": True, "deleted_id": int(domain_id)}
