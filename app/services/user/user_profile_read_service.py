from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import exc

from app.exceptions.forge_error import ForgeError
from app.models.tenancy.role import Role
from app.models.tenancy.status_enum import UserStatus
from app.models.tenancy.user import User
from app.models.tenancy.user_workspace import UserWorkspace
from app.ports.sql_executor import ForgeQueryPort

if TYPE_CHECKING:
    from app.services.user_service import UserService

logger = logging.getLogger(__name__)


class UserProfileReadService:
    def __init__(self, *, sql: ForgeQueryPort) -> None:
        self._sql = sql

    def get_counts(self, *, workspace_id: Optional[str] = None) -> Dict[str, int]:
        normalized_workspace_id = str(workspace_id or "").strip() or None
        sql = """
            SELECT u.status, COUNT(*) as count
            FROM users u
            WHERE u.status IS NOT NULL
        """
        params: Dict[str, Any] = {}
        if normalized_workspace_id:
            sql += """
              AND (
                    EXISTS (
                        SELECT 1
                        FROM workspace_membership wm
                        WHERE wm.user_id = u.user_id
                          AND wm.workspace_id = :workspace_id
                          AND COALESCE(wm.is_active, 1) = 1
                    )
                 OR EXISTS (
                        SELECT 1
                        FROM workspace w
                        JOIN organization_membership om
                          ON om.organization_id = w.organization_id
                         AND om.user_id = u.user_id
                         AND COALESCE(om.is_active, 1) = 1
                        WHERE w.id = :workspace_id
                          AND COALESCE(w.is_active, 1) = 1
                    )
              )
            """
            params["workspace_id"] = normalized_workspace_id
        sql += " GROUP BY u.status"

        try:
            results = self._sql.execute_query_mappings(sql, params)
            counts = {row["status"]: row["count"] for row in results}
            counts["All"] = sum(counts.values())

            for status in UserStatus:
                counts.setdefault(status.value, 0)

            return counts
        except exc.SQLAlchemyError as err:
            logger.error("%s - %s", sql, err)
            raise ForgeError(f"Database error: {str(err)}", 500) from err

    def find_user_by_username(
        self,
        service: "UserService",
        username: str,
        workspace_id: Optional[str] = None,
    ) -> Optional[User]:
        sql = """
            SELECT
                user_id,
                username,
                password,
                email,
                first_name,
                last_name,
                tos_accepted,
                eula_accepted,
                status AS user_status,
                otp_secret,
                last_log_in,
                two_factor_preference
            FROM users
            WHERE username = :username
            LIMIT 1
        """
        try:
            result = self._sql.execute_query_mappings(sql, {"username": username})
            if not result:
                return None
            user = service._map_user_row(result[0])
            user.workspaces = [UserWorkspace(**row) for row in service.get_user_workspaces(str(user.user_id))]
            direct_roles = service._to_role_models(
                service.get_user_direct_roles(str(user.user_id), workspace_id=workspace_id)
            )
            user.rbac_roles = direct_roles
            user.rbac_role_ids = [role.role_id for role in direct_roles]
            user.rbac_role_names = [role.role_name for role in direct_roles]
            return user
        except exc.SQLAlchemyError as err:
            logger.error("%s - %s", sql, err)
            raise ForgeError(f"Failed to retrieve user: {str(err)}", 500) from err

    def get_user(
        self,
        service: "UserService",
        user_id: str,
        workspace_id: Optional[str] = None,
    ) -> User:
        sql = """
            SELECT
                user_id,
                username,
                password,
                email,
                first_name,
                last_name,
                tos_accepted,
                eula_accepted,
                status AS user_status,
                otp_secret,
                last_log_in,
                two_factor_preference
            FROM users
            WHERE user_id = :user_id
            LIMIT 1
        """
        try:
            result = self._sql.execute_query_mappings(sql, {"user_id": user_id})
            if not result:
                logger.error("User not found %s", user_id)
                raise ForgeError("User not found", 404)
            if workspace_id and not service._user_is_visible_in_workspace(str(user_id), workspace_id):
                logger.error("User not found in workspace scope %s %s", user_id, workspace_id)
                raise ForgeError("User not found", 404)
            user = service._map_user_row(result[0])
            user.workspaces = [
                UserWorkspace(**row)
                for row in service.get_user_workspaces(str(user.user_id), scope_workspace_id=workspace_id)
            ]
            direct_roles = service._to_role_models(
                service.get_user_direct_roles(str(user.user_id), workspace_id=workspace_id)
            )
            user.rbac_roles = direct_roles
            user.rbac_role_ids = [role.role_id for role in direct_roles]
            user.rbac_role_names = [role.role_name for role in direct_roles]
            return user
        except exc.SQLAlchemyError as err:
            logger.error("%s - %s", sql, err)
            raise ForgeError(f"Failed to retrieve user: {str(err)}", 500) from err

    def get_users(
        self,
        service: "UserService",
        status: str = "All",
        cursor: Optional[str] = None,
        limit: int = 10,
        direction: str = "forward",
        username: Optional[str] = None,
        *,
        workspace_id: Optional[str] = None,
    ) -> tuple:
        normalized_workspace_id = str(workspace_id or "").strip() or None
        where_clauses = ["(:status = 'All' OR u.status = :status)", "u.status IS NOT NULL"]
        params = {"status": status, "limit": limit + 1}

        if username:
            q = str(username or "").strip().lower()
            where_clauses.append(
                """
                (
                    LOWER(COALESCE(u.username, '')) LIKE :username
                    OR LOWER(COALESCE(u.email, '')) LIKE :username
                    OR LOWER(COALESCE(u.first_name, '')) LIKE :username
                    OR LOWER(COALESCE(u.last_name, '')) LIKE :username
                    OR LOWER(CONCAT_WS(' ', COALESCE(u.first_name, ''), COALESCE(u.last_name, ''))) LIKE :username
                )
                """
            )
            params["username"] = f"%{q}%"

        if normalized_workspace_id:
            where_clauses.append(
                """
                (
                    EXISTS (
                        SELECT 1
                        FROM workspace_membership wm
                        WHERE wm.user_id = u.user_id
                          AND wm.workspace_id = :workspace_id
                          AND COALESCE(wm.is_active, 1) = 1
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM workspace w
                        JOIN organization_membership om
                          ON om.organization_id = w.organization_id
                         AND om.user_id = u.user_id
                         AND COALESCE(om.is_active, 1) = 1
                        WHERE w.id = :workspace_id
                          AND COALESCE(w.is_active, 1) = 1
                    )
                )
                """
            )
            params["workspace_id"] = normalized_workspace_id

        where_clause = " AND ".join(where_clauses)

        if cursor:
            if direction == "forward":
                where_clause += " AND u.user_id > :cursor"
                params["cursor"] = cursor
                order_by = "ORDER BY u.user_id ASC"
            else:
                where_clause += " AND u.user_id < :cursor"
                params["cursor"] = cursor
                order_by = "ORDER BY u.user_id ASC"
        else:
            order_by = "ORDER BY u.user_id ASC"

        base_user_query = f"""
            SELECT u.user_id, u.username, u.first_name, u.last_name, u.email, u.status, u.tos_accepted,
                u.eula_accepted, u.two_factor_preference, u.last_log_in
            FROM users u
            WHERE {where_clause}
            {order_by}
            LIMIT :limit
        """

        base_rows = self._sql.execute_query_mappings(base_user_query, params)

        if not base_rows:
            return [], None, None, 0

        trimmed = base_rows[:limit]
        user_ids = [row["user_id"] for row in trimmed]

        workspace_map = service._get_user_workspaces_bulk(user_ids)

        users = []
        for base_row in trimmed:
            uid = base_row["user_id"]
            row_dict = dict(base_row)
            row_dict["tos_accepted"] = bool(row_dict.get("tos_accepted"))
            row_dict["eula_accepted"] = bool(row_dict.get("eula_accepted"))

            workspaces = [
                UserWorkspace(workspace_id=row.get("workspace_id"), is_default=bool(row.get("is_default")))
                for row in workspace_map.get(str(uid), [])
            ]

            users.append(User(**row_dict, workspaces=workspaces))

        direct_roles_map = service.get_direct_roles_for_users(user_ids, workspace_id=workspace_id)
        for user in users:
            role_rows = direct_roles_map.get(str(user.user_id), [])
            role_models = service._to_role_models(role_rows)
            user.rbac_roles = role_models
            user.rbac_role_ids = [role.role_id for role in role_models]
            user.rbac_role_names = [role.role_name for role in role_models]

        next_cursor = None
        prev_cursor = None

        if len(base_rows) > limit:
            next_cursor = base_rows[limit - 1]["user_id"]
        if direction == "forward" and cursor:
            prev_query = f"""
                SELECT u.user_id
                FROM users u
                WHERE {where_clause.replace('u.user_id > :cursor', 'u.user_id < :cursor')}
                ORDER BY u.user_id DESC
                LIMIT 1
            """
            prev_rows = self._sql.execute_query_mappings(prev_query, {**params, "limit": None})
            prev_result = prev_rows[0] if prev_rows else None
            if prev_result:
                prev_cursor = prev_result["user_id"]
        elif direction == "backward" and len(users) > 0:
            next_cursor = users[0].user_id
            users = users[::-1]
            prev_query = f"""
                SELECT u.user_id
                FROM users u
                WHERE {where_clause.replace('u.user_id < :cursor', 'u.user_id < :cursor')}
                ORDER BY u.user_id DESC
                LIMIT 1
            """
            prev_rows = self._sql.execute_query_mappings(
                prev_query,
                {**params, "cursor": users[0].user_id, "limit": None},
            )
            prev_result = prev_rows[0] if prev_rows else None
            if prev_result:
                prev_cursor = prev_result["user_id"]

        count_query = f"SELECT COUNT(*) as count FROM users u WHERE {' AND '.join(where_clauses)}"
        count_params = {k: v for k, v in params.items() if k not in {"limit", "cursor"}}
        count_rows = self._sql.execute_query_mappings(count_query, count_params)
        total_count = count_rows[0].get("count") if count_rows else 0

        return users, next_cursor, prev_cursor, total_count

    def check_for_existing_user(self, username: str) -> bool:
        sql = "SELECT * FROM users WHERE username = :username"
        try:
            logging.info("Checking for existing user: %s", username)
            result = self._sql.execute_query_mappings(sql, {"username": username})
            if len(result) > 0:
                logging.info("User %s exists.", username)
                return True
            logging.info("User %s does not exist.", username)
            return False
        except exc.SQLAlchemyError as err:
            logger.error("%s - %s", sql, err)
            raise ForgeError(f"Failed to retrieve user workspaces: {str(err)}", 500) from err

    @staticmethod
    def map_user_row(base_row: Dict[str, Any]) -> User:
        user_data = {
            "user_id": base_row["user_id"],
            "user_name": base_row.get("username"),
            "password": base_row.get("password"),
            "first_name": base_row.get("first_name"),
            "last_name": base_row.get("last_name"),
            "email": base_row.get("email"),
            "status": base_row.get("user_status"),
            "tos_accepted": base_row.get("tos_accepted"),
            "eula_accepted": base_row.get("eula_accepted"),
            "otp_secret": base_row.get("otp_secret"),
            "two_factor_preference": base_row.get("two_factor_preference"),
            "last_log_in": base_row.get("last_log_in"),
        }
        return User(**user_data, workspaces=[])

    @staticmethod
    def to_role_models(rows: List[Dict[str, Any]]) -> List[Role]:
        out: List[Role] = []
        seen = set()
        for row in rows or []:
            role_id = str(row.get("role_id") or "").strip()
            role_name = str(row.get("role_name") or "").strip()
            if not role_id or not role_name:
                continue
            if role_id in seen:
                continue
            seen.add(role_id)
            out.append(Role(role_id=role_id, role_name=role_name))
        return out

    def update_last_login(self, user_id: str) -> None:
        sql = """
            UPDATE users
            SET last_log_in = :now
            WHERE user_id = :user_id
        """
        with self._sql.transaction() as tx:
            tx.execute_write(sql, {"now": datetime.now(timezone.utc), "user_id": user_id})
