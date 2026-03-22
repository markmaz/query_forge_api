from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.shared.jsonify import serialize_record

_ALLOWED_POLICIES = frozenset({"DEDUP_PRIMARY_FIRST", "SHOW_ALL_QUALIFIED"})


class _DomainAdminStore:
    def __init__(self, *, sql: ForgeQueryPort) -> None:
        self._sql = sql

    def _exists(self, query: str, params: Dict[str, Any]) -> bool:
        return bool(self._sql.execute_query(query, params))

    def any_domain_exists(self, *, workspace_id: str) -> bool:
        return self._exists(
            """
            SELECT 1
            FROM domain d
            WHERE d.workspace_id=:ws
            LIMIT 1
            """,
            {"ws": workspace_id},
        )

    def user_has_any_edit(self, *, workspace_id: str, user_id: str) -> bool:
        return self._exists(
            """
            SELECT 1
            FROM user_domain_mapping udm
            JOIN domain d ON d.id = udm.domain_id
            WHERE d.workspace_id=:ws
              AND d.is_active=1
              AND udm.user_id=:uid
              AND udm.can_edit=1
            LIMIT 1
            """,
            {"ws": workspace_id, "uid": user_id},
        )

    def user_can_edit_domain(self, *, workspace_id: str, user_id: str, domain_id: int) -> bool:
        return self._exists(
            """
            SELECT 1
            FROM user_domain_mapping udm
            JOIN domain d ON d.id = udm.domain_id
            WHERE d.workspace_id=:ws
              AND d.id=:did
              AND d.is_active=1
              AND udm.user_id=:uid
              AND udm.can_edit=1
            LIMIT 1
            """,
            {"ws": workspace_id, "did": int(domain_id), "uid": user_id},
        )

    def create_domain_with_owner(
        self,
        *,
        workspace_id: str,
        user_id: str,
        name: str,
        kind: Optional[str],
        description: Optional[str],
        model_table_id: Optional[int],
        column_name_policy: Optional[str],
    ) -> int:
        del model_table_id
        with self._sql.transaction() as tx:
            tx.execute_write(
                """
                INSERT INTO workspace (id, display_name)
                VALUES (:id, :display_name)
                ON DUPLICATE KEY UPDATE id=id
                """,
                {"id": workspace_id, "display_name": None},
            )

            result = tx.execute_insert(
                """
                INSERT INTO domain (
                    workspace_id, name, kind, description, model_table_id,
                    column_name_policy, is_active, created_at
                )
                VALUES (:ws, :name, :kind, :desc, NULL, :policy, 1, CURRENT_TIMESTAMP)
                """,
                {
                    "ws": workspace_id,
                    "name": name,
                    "kind": kind,
                    "desc": description,
                    "policy": column_name_policy,
                },
            )
            domain_id = int(result.lastrowid or 0)

            tx.execute_write(
                """
                INSERT INTO user_domain_mapping (user_id, domain_id, can_read, can_edit, created_at)
                VALUES (:uid, :did, 1, 1, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE can_read=1, can_edit=1
                """,
                {"uid": user_id, "did": domain_id},
            )

        return domain_id

    def update_domain(
        self,
        *,
        workspace_id: str,
        domain_id: int,
        set_clauses: List[str],
        params: Dict[str, Any],
    ) -> None:
        with self._sql.transaction() as tx:
            tx.execute_write(
                f"""
                UPDATE domain
                SET {", ".join(set_clauses)}, updated_at=CURRENT_TIMESTAMP
                WHERE workspace_id=:ws AND id=:did
                """,
                params,
            )

    def fetch_domain_row(self, *, workspace_id: str, domain_id: int) -> Optional[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              d.id,
              d.name,
              d.kind,
              d.description,
              NULL AS model_table_id,
              d.column_name_policy,
              (
                SELECT COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name)
                FROM domain_workspace_table dwt2
                JOIN workspace_table wt ON wt.id = dwt2.workspace_table_id
                WHERE dwt2.domain_id = d.id
                ORDER BY dwt2.is_primary DESC, dwt2.sort_order ASC, wt.id ASC
                LIMIT 1
              ) AS model_table_name,
              d.is_active,
              d.created_at,
              d.updated_at
            FROM domain d
            WHERE d.workspace_id=:ws AND d.id=:did
            """,
            {"ws": workspace_id, "did": int(domain_id)},
        )
        return dict(rows[0]) if rows else None

    def delete_domain(self, *, workspace_id: str, domain_id: int) -> int:
        with self._sql.transaction() as tx:
            return tx.execute_write(
                "DELETE FROM domain WHERE workspace_id=:ws AND id=:did",
                {"ws": workspace_id, "did": int(domain_id)},
            )


class DomainAdminWriteService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._store = _DomainAdminStore(sql=self._sql)

    @staticmethod
    def _normalize_policy(value: Optional[str]) -> Optional[str]:
        policy = (value or "").strip().upper() or None
        if policy and policy not in _ALLOWED_POLICIES:
            raise ForgeError("Invalid column_name_policy", status_code=400)
        return policy

    @staticmethod
    def _clean_required_name(name: str) -> str:
        clean_name = (name or "").strip()
        if not clean_name:
            raise ForgeError("name is required", status_code=400)
        return clean_name

    @staticmethod
    def _clean_optional_text(value: Optional[str]) -> Optional[str]:
        return (value or "").strip() or None

    def _can_edit_any(self, *, workspace_id: str, user_id: str) -> bool:
        # First domain in a workspace can be created without an existing mapping.
        if not self._store.any_domain_exists(workspace_id=workspace_id):
            return True
        return self._store.user_has_any_edit(workspace_id=workspace_id, user_id=user_id)

    def _assert_can_edit_any(self, *, workspace_id: str, user_id: str) -> None:
        if not self._can_edit_any(workspace_id=workspace_id, user_id=user_id):
            raise ForgeError("You do not have permission to create domains.", status_code=403)

    def _assert_can_edit_domain(self, *, workspace_id: str, user_id: str, domain_id: int) -> None:
        if not self._store.user_can_edit_domain(workspace_id=workspace_id, user_id=user_id, domain_id=domain_id):
            raise ForgeError("You do not have edit permission for this domain.", status_code=403)

    def create_domain(
        self,
        *,
        workspace_id: str,
        user_id: str,
        name: str,
        kind: Optional[str] = None,
        description: Optional[str] = None,
        model_table_id: Optional[int] = None,
        column_name_policy: Optional[str] = None,
        bypass_permissions: bool = False,
    ) -> Dict[str, Any]:
        if not bypass_permissions:
            self._assert_can_edit_any(workspace_id=workspace_id, user_id=user_id)

        clean_name = self._clean_required_name(name)
        clean_kind = self._clean_optional_text(kind)
        clean_description = self._clean_optional_text(description)
        normalized_policy = self._normalize_policy(column_name_policy)
        # model_table_id is intentionally ignored in workspace-first mode.
        clean_model_table_id = None

        domain_id = self._store.create_domain_with_owner(
            workspace_id=workspace_id,
            user_id=user_id,
            name=clean_name,
            kind=clean_kind,
            description=clean_description,
            model_table_id=clean_model_table_id,
            column_name_policy=normalized_policy,
        )

        row = self._store.fetch_domain_row(workspace_id=workspace_id, domain_id=domain_id)
        if row:
            return serialize_record(row)

        return {
            "id": domain_id,
            "name": clean_name,
            "kind": clean_kind,
            "description": clean_description,
            "modelTableId": clean_model_table_id,
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
        model_table_id: Optional[int] = None,
        column_name_policy: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._assert_can_edit_domain(workspace_id=workspace_id, user_id=user_id, domain_id=domain_id)

        params: Dict[str, Any] = {"ws": workspace_id, "did": int(domain_id)}
        set_clauses: List[str] = []

        if name is not None:
            clean_name = name.strip()
            if not clean_name:
                raise ForgeError("name cannot be empty", status_code=400)
            params["name"] = clean_name
            set_clauses.append("name=:name")

        if kind is not None:
            params["kind"] = self._clean_optional_text(kind)
            set_clauses.append("kind=:kind")

        if description is not None:
            params["description"] = self._clean_optional_text(description)
            set_clauses.append("description=:description")

        if is_active is not None:
            params["is_active"] = 1 if is_active else 0
            set_clauses.append("is_active=:is_active")

        if model_table_id is not None:
            # Ignore legacy model_table_id field in workspace-first mode.
            pass

        if column_name_policy is not None:
            params["column_name_policy"] = self._normalize_policy(column_name_policy)
            set_clauses.append("column_name_policy=:column_name_policy")

        if not set_clauses:
            raise ForgeError("No fields to update", status_code=400)

        self._store.update_domain(
            workspace_id=workspace_id,
            domain_id=int(domain_id),
            set_clauses=set_clauses,
            params=params,
        )

        row = self._store.fetch_domain_row(workspace_id=workspace_id, domain_id=int(domain_id))
        if not row:
            raise ForgeError("Domain not found", status_code=404)
        return serialize_record(row)

    def delete_domain(self, *, workspace_id: str, user_id: str, domain_id: int) -> Dict[str, Any]:
        self._assert_can_edit_domain(workspace_id=workspace_id, user_id=user_id, domain_id=domain_id)

        deleted = self._store.delete_domain(workspace_id=workspace_id, domain_id=int(domain_id))
        if deleted == 0:
            raise ForgeError("Domain not found", status_code=404)

        return {"ok": True, "deleted_id": int(domain_id)}
