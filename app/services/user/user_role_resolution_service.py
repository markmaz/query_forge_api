from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from sqlalchemy import exc

from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort, ForgeQueryTx

if TYPE_CHECKING:
    from app.services.user_service import UserService

logger = logging.getLogger(__name__)


class UserRoleResolutionService:
    def __init__(self, *, sql: ForgeQueryPort) -> None:
        self._sql = sql

    def get_user_direct_roles(self, user_id: str, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        normalized_workspace_id = str(workspace_id or "").strip() or None
        sql = """
            SELECT
                CAST(r.id AS CHAR) AS role_id,
                r.name AS role_name,
                r.display_name,
                r.description,
                r.feature_key,
                r.is_system
            FROM user_roles ur
            JOIN roles r ON r.id = ur.role_id
            WHERE ur.user_id = :user_id
              AND (
                    (ur.workspace_id <=> :workspace_id)
                 OR (ur.workspace_id IS NULL AND r.name = 'super_admin')
              )
            ORDER BY r.name
        """
        try:
            return [
                dict(row)
                for row in self._sql.execute_query_mappings(
                    sql,
                    {"user_id": user_id, "workspace_id": normalized_workspace_id},
                )
            ]
        except exc.SQLAlchemyError as err:
            logger.error("Error fetching direct roles for user_id=%s: %s", user_id, err)
            raise ForgeError(f"Failed to retrieve user direct roles: {str(err)}", 500) from err

    def get_role_by_name(self, role_name: str) -> Dict[str, Any]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
                id,
                CAST(id AS CHAR) AS role_id,
                name AS role_name,
                display_name,
                description,
                feature_key,
                is_system
            FROM roles
            WHERE name = :role_name
            LIMIT 1
            """,
            {"role_name": str(role_name)},
        )
        if not rows:
            raise ForgeError("Role not found", 404)
        return dict(rows[0])

    def assert_user_exists(self, user_id: str) -> None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT user_id
            FROM users
            WHERE user_id = :user_id
            LIMIT 1
            """,
            {"user_id": str(user_id)},
        )
        if not rows:
            raise ForgeError("User not found", 404)

    def assert_role_exists(self, role_name: str) -> None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT id
            FROM roles
            WHERE name = :role_name
            LIMIT 1
            """,
            {"role_name": str(role_name)},
        )
        if not rows:
            raise ForgeError("Role not found", 404)

    def get_roles_by_names(
        self,
        role_names: List[str],
        *,
        tx: Optional[ForgeQueryTx] = None,
    ) -> Dict[str, Dict[str, Any]]:
        names = [str(name or "").strip() for name in role_names if str(name or "").strip()]
        if not names:
            return {}
        placeholders = ",".join([f":name{i}" for i in range(len(names))])
        params = {f"name{i}": name for i, name in enumerate(names)}
        query = f"""
            SELECT
                id,
                CAST(id AS CHAR) AS role_id,
                name AS role_name,
                display_name,
                description,
                feature_key,
                is_system
            FROM roles
            WHERE name IN ({placeholders})
        """
        executor = tx.execute_query_mappings if tx is not None else self._sql.execute_query_mappings
        rows = executor(query, params)
        return {
            str(row.get("role_name") or "").strip(): dict(row)
            for row in rows
            if str(row.get("role_name") or "").strip()
        }

    @staticmethod
    def normalize_role_workspace(role_name: str, workspace_id: Optional[str]) -> Optional[str]:
        role_name = str(role_name or "").strip()
        normalized_workspace_id = str(workspace_id or "").strip() or None
        if role_name == "super_admin":
            return None
        if not normalized_workspace_id:
            raise ForgeError("workspace_id is required for non-global roles", 400)
        return normalized_workspace_id

    def add_user_direct_role(
        self,
        user_id: str,
        role_name: str,
        workspace_id: Optional[str] = None,
        tx: Optional[ForgeQueryTx] = None,
    ) -> Dict[str, Any]:
        uid = str(user_id or "").strip()
        role_name = str(role_name or "").strip()
        self.assert_user_exists(uid)
        role = self.get_role_by_name(role_name)
        role_id = int(role.get("id") or role.get("role_id"))
        normalized_workspace_id = self.normalize_role_workspace(role_name, workspace_id)

        try:
            if tx is None:
                result: Dict[str, Any]
                with self._sql.transaction() as local_tx:
                    exists_rows = local_tx.execute_query_mappings(
                        """
                        SELECT id
                        FROM user_roles
                        WHERE user_id = :user_id
                          AND role_id = :role_id
                          AND workspace_id <=> :workspace_id
                        LIMIT 1
                        """,
                        {
                            "user_id": uid,
                            "role_id": role_id,
                            "workspace_id": normalized_workspace_id,
                        },
                    )
                    if exists_rows:
                        result = {
                            "user_id": uid,
                            "workspace_id": normalized_workspace_id,
                            "role_name": role_name,
                            "created": False,
                        }
                    else:
                        local_tx.execute_write(
                            """
                            INSERT INTO user_roles (user_id, workspace_id, role_id)
                            VALUES (:user_id, :workspace_id, :role_id)
                            """,
                            {
                                "user_id": uid,
                                "workspace_id": normalized_workspace_id,
                                "role_id": role_id,
                            },
                        )
                        result = {
                            "user_id": uid,
                            "workspace_id": normalized_workspace_id,
                            "role_name": role_name,
                            "created": True,
                        }

                from app.services.rbac_service import invalidate_user_roles

                invalidate_user_roles(uid, workspace_id=normalized_workspace_id)
                return result

            exists_rows = tx.execute_query_mappings(
                """
                SELECT id
                FROM user_roles
                WHERE user_id = :user_id
                  AND role_id = :role_id
                  AND workspace_id <=> :workspace_id
                LIMIT 1
                """,
                {
                    "user_id": uid,
                    "role_id": role_id,
                    "workspace_id": normalized_workspace_id,
                },
            )
            if exists_rows:
                return {
                    "user_id": uid,
                    "workspace_id": normalized_workspace_id,
                    "role_name": role_name,
                    "created": False,
                }

            tx.execute_write(
                """
                INSERT INTO user_roles (user_id, workspace_id, role_id)
                VALUES (:user_id, :workspace_id, :role_id)
                """,
                {
                    "user_id": uid,
                    "workspace_id": normalized_workspace_id,
                    "role_id": role_id,
                },
            )
            return {
                "user_id": uid,
                "workspace_id": normalized_workspace_id,
                "role_name": role_name,
                "created": True,
            }
        except ForgeError:
            raise
        except exc.SQLAlchemyError as err:
            logger.error("Error adding direct role for user_id=%s: %s", uid, err)
            raise ForgeError(f"Failed to add user direct role: {str(err)}", 500) from err

    def remove_user_direct_role(
        self,
        user_id: str,
        role_name: str,
        workspace_id: Optional[str] = None,
        tx: Optional[ForgeQueryTx] = None,
    ) -> Dict[str, Any]:
        uid = str(user_id or "").strip()
        role_name = str(role_name or "").strip()
        self.assert_user_exists(uid)
        role = self.get_role_by_name(role_name)
        role_id = int(role.get("id") or role.get("role_id"))
        normalized_workspace_id = self.normalize_role_workspace(role_name, workspace_id)

        try:
            if tx is None:
                result: Dict[str, Any]
                with self._sql.transaction() as local_tx:
                    deleted = local_tx.execute_write(
                        """
                        DELETE FROM user_roles
                        WHERE user_id = :user_id
                          AND role_id = :role_id
                          AND workspace_id <=> :workspace_id
                        """,
                        {
                            "user_id": uid,
                            "role_id": role_id,
                            "workspace_id": normalized_workspace_id,
                        },
                    )
                    if int(deleted or 0) == 0:
                        raise ForgeError("User direct role mapping not found", 404)
                    result = {
                        "user_id": uid,
                        "workspace_id": normalized_workspace_id,
                        "role_name": role_name,
                        "deleted": True,
                    }
                from app.services.rbac_service import invalidate_user_roles

                invalidate_user_roles(uid, workspace_id=normalized_workspace_id)
                return result

            deleted = tx.execute_write(
                """
                DELETE FROM user_roles
                WHERE user_id = :user_id
                  AND role_id = :role_id
                  AND workspace_id <=> :workspace_id
                """,
                {
                    "user_id": uid,
                    "role_id": role_id,
                    "workspace_id": normalized_workspace_id,
                },
            )
            if int(deleted or 0) == 0:
                raise ForgeError("User direct role mapping not found", 404)

            return {
                "user_id": uid,
                "workspace_id": normalized_workspace_id,
                "role_name": role_name,
                "deleted": True,
            }
        except ForgeError:
            raise
        except exc.SQLAlchemyError as err:
            logger.error("Error removing direct role for user_id=%s: %s", uid, err)
            raise ForgeError(f"Failed to remove user direct role: {str(err)}", 500) from err

    def replace_user_direct_roles(
        self,
        service: "UserService",
        user_id: str,
        role_names: List[str],
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        uid = str(user_id or "").strip()
        self.assert_user_exists(uid)

        normalized_role_names: List[str] = []
        seen = set()
        for role_name in role_names or []:
            name = str(role_name or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            normalized_role_names.append(name)

        for name in normalized_role_names:
            self.assert_role_exists(name)

        try:
            with self._sql.transaction() as tx:
                self.sync_user_direct_roles(
                    service,
                    tx,
                    uid,
                    normalized_role_names,
                    workspace_id=workspace_id,
                )
            from app.services.rbac_service import invalidate_user_roles

            invalidate_user_roles(uid, workspace_id=str(workspace_id or "").strip() or None)
            roles = self.get_user_direct_roles(uid, workspace_id=workspace_id)
            return {
                "user_id": uid,
                "workspace_id": str(workspace_id or "").strip() or None,
                "roles": roles,
                "count": len(roles),
            }
        except ForgeError:
            raise
        except exc.SQLAlchemyError as err:
            logger.error("Error replacing direct roles for user_id=%s: %s", uid, err)
            raise ForgeError(f"Failed to replace user direct roles: {str(err)}", 500) from err

    def update_user_direct_role(
        self,
        service: "UserService",
        user_id: str,
        old_role_name: str,
        new_role_name: str,
        workspace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        uid = str(user_id or "").strip()
        old_role_name = str(old_role_name or "").strip()
        new_role_name = str(new_role_name or "").strip()
        self.assert_user_exists(uid)
        self.assert_role_exists(new_role_name)

        try:
            with self._sql.transaction() as tx:
                service.remove_user_direct_role(uid, old_role_name, workspace_id=workspace_id, tx=tx)
                created = service.add_user_direct_role(uid, new_role_name, workspace_id=workspace_id, tx=tx)
            from app.services.rbac_service import invalidate_user_roles

            invalidate_user_roles(
                uid,
                workspace_id=self.normalize_role_workspace(new_role_name, workspace_id),
            )
            return {
                "user_id": uid,
                "workspace_id": str(workspace_id or "").strip() or None,
                "old_role_name": old_role_name,
                "new_role_name": new_role_name,
                "created": bool(created.get("created")),
            }
        except ForgeError:
            raise
        except exc.SQLAlchemyError as err:
            logger.error("Error updating direct role for user_id=%s: %s", uid, err)
            raise ForgeError(f"Failed to update user direct role: {str(err)}", 500) from err

    def get_direct_roles_for_users(
        self,
        user_ids: List[str],
        workspace_id: Optional[str] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        ids = [str(uid or "").strip() for uid in user_ids if str(uid or "").strip()]
        if not ids:
            return {}
        normalized_workspace_id = str(workspace_id or "").strip() or None
        placeholders = ",".join([f":uid{i}" for i in range(len(ids))])
        params = {f"uid{i}": uid for i, uid in enumerate(ids)}
        params["workspace_id"] = normalized_workspace_id
        sql = f"""
            SELECT
                ur.user_id,
                CAST(r.id AS CHAR) AS role_id,
                r.name AS role_name,
                r.display_name,
                r.description,
                r.feature_key,
                r.is_system
            FROM user_roles ur
            JOIN roles r ON r.id = ur.role_id
            WHERE ur.user_id IN ({placeholders})
              AND (
                    (ur.workspace_id <=> :workspace_id)
                 OR (ur.workspace_id IS NULL AND r.name = 'super_admin')
              )
            ORDER BY ur.user_id, r.name
        """
        try:
            rows = self._sql.execute_query_mappings(sql, params)
        except exc.SQLAlchemyError as err:
            logger.error("Error fetching direct roles for users: %s", err)
            raise ForgeError(f"Failed to retrieve user direct roles: {str(err)}", 500) from err

        out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for row in rows:
            uid = str(row.get("user_id") or "").strip()
            if uid:
                out[uid].append(dict(row))
        return out

    def get_user_effective_roles(self, user_id: str, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        from app.services.rbac_service import get_effective_roles

        role_names = sorted(get_effective_roles(str(user_id or "").strip(), workspace_id=workspace_id))
        if not role_names:
            return []

        roles_by_name = self.get_roles_by_names(role_names)
        return [roles_by_name[name] for name in role_names if name in roles_by_name]

    def get_user_effective_role_names(
        self,
        service: "UserService",
        user_id: str,
        workspace_id: Optional[str] = None,
    ) -> List[str]:
        roles = service.get_user_effective_roles(user_id, workspace_id=workspace_id)
        names: List[str] = []
        seen = set()
        for row in roles:
            role_name = str(row.get("role_name") or "").strip()
            if not role_name:
                continue
            key = role_name.lower()
            if key in seen:
                continue
            seen.add(key)
            names.append(role_name)
        return names

    def sync_user_direct_roles(
        self,
        service: "UserService",
        tx: ForgeQueryTx,
        user_id: str,
        new_role_names: List[str],
        *,
        workspace_id: Optional[str] = None,
    ) -> None:
        desired_role_names: Set[str] = {
            str(role_name or "").strip()
            for role_name in (new_role_names or [])
            if str(role_name or "").strip()
        }
        normalized_workspace_id = str(workspace_id or "").strip() or None
        if any(role_name != "super_admin" for role_name in desired_role_names) and not normalized_workspace_id:
            raise ForgeError("workspace_id is required for non-global roles", 400)

        rows = tx.execute_query_mappings(
            """
            SELECT r.id, r.name AS role_name
            FROM user_roles ur
            JOIN roles r ON r.id = ur.role_id
            WHERE ur.user_id = :uid
              AND (
                    (ur.workspace_id <=> :workspace_id)
                 OR (ur.workspace_id IS NULL AND r.name = 'super_admin')
              )
            """,
            {"uid": user_id, "workspace_id": normalized_workspace_id},
        )
        existing_role_names = {
            str(row.get("role_name") or "").strip()
            for row in rows
            if str(row.get("role_name") or "").strip()
        }

        to_delete = sorted(existing_role_names - desired_role_names)
        to_insert = sorted(desired_role_names - existing_role_names)

        for role_name in to_delete:
            service.remove_user_direct_role(
                user_id,
                role_name,
                workspace_id=normalized_workspace_id,
                tx=tx,
            )

        for role_name in to_insert:
            service.add_user_direct_role(
                user_id,
                role_name,
                workspace_id=normalized_workspace_id,
                tx=tx,
            )
