from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import exc

from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort, ForgeQueryTx

if TYPE_CHECKING:
    from app.services.user_service import UserService

logger = logging.getLogger(__name__)


class UserWorkspaceAccessService:
    def __init__(self, *, sql: ForgeQueryPort) -> None:
        self._sql = sql

    def map_user_workspace(
        self,
        service: "UserService",
        user_id: str,
        workspace_id: str,
        is_default: bool,
        tx: Optional[ForgeQueryTx] = None,
    ) -> Dict[str, Any]:
        mapping = service.get_user_workspaces(user_id)

        if any(str(w.get("workspace_id")) == str(workspace_id) for w in mapping):
            logger.error("User: %s already mapped to workspace %s", user_id, workspace_id)
            raise ForgeError("Mapping already exists for user", 409)

        try:
            if tx is None:
                with self._sql.transaction() as local_tx:
                    return self.map_user_workspace(service, user_id, workspace_id, is_default, local_tx)

            if not mapping:
                is_default = True
            elif is_default:
                update_sql = """
                    UPDATE workspace_membership
                    SET is_default = false
                    WHERE user_id = :user_id AND is_default = true
                """
                tx.execute_write(update_sql, {"user_id": user_id})

            insert_sql = """
                INSERT INTO workspace_membership (workspace_id, user_id, role, is_active, is_default)
                VALUES (:workspace_id, :user_id, 'member', 1, :is_default)
                ON DUPLICATE KEY UPDATE
                  is_active = 1,
                  is_default = VALUES(is_default),
                  updated_at = CURRENT_TIMESTAMP
            """
            tx.execute_write(
                insert_sql,
                {
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                    "is_default": 1 if is_default else 0,
                },
            )

            return {
                "message": "User and workspace mapped successfully",
                "mapping": {
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                    "is_default": is_default,
                },
            }
        except exc.SQLAlchemyError as err:
            logger.error("SQL error during user mapping: %s", err)
            raise ForgeError(f"Failed to map user to workspace: {str(err)}", 500) from err

    def sync_user_workspaces(self, tx: ForgeQueryTx, user_id: str, new_ws: List[Dict[str, Any]]) -> None:
        desired = {
            str(w["workspace_id"]): bool(w.get("is_default", False))
            for w in (new_ws or [])
        }
        if desired and not any(desired.values()):
            first_key = next(iter(desired.keys()))
            desired[first_key] = True

        rows = tx.execute_query_mappings(
            """
            SELECT workspace_id, COALESCE(is_default, 0) AS is_default
            FROM workspace_membership
            WHERE user_id = :uid
            """,
            {"uid": user_id},
        )
        existing = {str(r["workspace_id"]): bool(r["is_default"]) for r in rows}

        to_delete = set(existing) - set(desired)
        to_insert = set(desired) - set(existing)
        to_update = {wid for wid in existing.keys() & desired.keys() if existing[wid] != desired[wid]}

        if to_delete:
            ids_list = list(to_delete)
            placeholders = ",".join([f":id{i}" for i in range(len(ids_list))])
            params = {"uid": user_id, **{f"id{i}": wid for i, wid in enumerate(ids_list)}}
            tx.execute_write(
                f"DELETE FROM workspace_membership WHERE user_id = :uid AND workspace_id IN ({placeholders})",
                params,
            )

        if to_insert:
            for wid in to_insert:
                tx.execute_write(
                    """
                    INSERT INTO workspace_membership (workspace_id, user_id, role, is_active, is_default)
                    VALUES (:workspace_id, :uid, 'member', 1, :is_default)
                    ON DUPLICATE KEY UPDATE
                      is_active = 1,
                      is_default = VALUES(is_default),
                      updated_at = CURRENT_TIMESTAMP
                    """,
                    {"uid": user_id, "workspace_id": wid, "is_default": 1 if desired[wid] else 0},
                )

        for wid in to_update:
            tx.execute_write(
                "UPDATE workspace_membership "
                "SET is_default = :is_default "
                "WHERE user_id = :uid AND workspace_id = :workspace_id",
                {"uid": user_id, "workspace_id": wid, "is_default": 1 if desired[wid] else 0},
            )
        if any(desired.values()):
            true_ids = [wid for wid, is_def in desired.items() if is_def]
            keep = true_ids[0]
            if len(true_ids) > 1:
                tx.execute_write(
                    "UPDATE workspace_membership SET is_default = 0 "
                    "WHERE user_id = :uid AND workspace_id != :keep",
                    {"uid": user_id, "keep": keep},
                )

    def set_workspace_default(
        self,
        service: "UserService",
        user_id: str,
        workspace_id: str,
        is_default: bool,
    ) -> Dict[str, str]:
        mapping = service.get_user_workspaces(user_id)
        current_mapping = next((w for w in mapping if w["workspace_id"] == workspace_id), None)

        if not current_mapping:
            raise ForgeError("Workspace mapping not found for user", 404)

        if current_mapping["is_default"] and not is_default:
            raise ForgeError("User must always have a default workspace", 409)

        try:
            with self._sql.transaction() as tx:
                if is_default:
                    unset_sql = """
                        UPDATE workspace_membership
                        SET is_default = false
                        WHERE user_id = :user_id
                    """
                    tx.execute_write(unset_sql, {"user_id": user_id})
                    tx.execute_write(
                        """
                        INSERT INTO workspace_membership (workspace_id, user_id, role, is_active, is_default)
                        VALUES (:workspace_id, :user_id, 'member', 1, 1)
                        ON DUPLICATE KEY UPDATE
                          is_active = 1,
                          is_default = 1,
                          updated_at = CURRENT_TIMESTAMP
                        """,
                        {"user_id": user_id, "workspace_id": workspace_id},
                    )
                else:
                    tx.execute_write(
                        """
                        UPDATE workspace_membership
                        SET is_default = 0
                        WHERE user_id = :user_id AND workspace_id = :workspace_id
                        """,
                        {"user_id": user_id, "workspace_id": workspace_id},
                    )

            return {
                "message": "Workspace default updated successfully",
                "mapping": {
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                    "is_default": is_default,
                },
            }

        except exc.SQLAlchemyError as err:
            logger.error("SQL error during workspace update: %s", err)
            raise ForgeError(f"Failed to update workspace mapping: {str(err)}", 500) from err

    def get_user_workspaces(
        self,
        service: "UserService",
        user_id: str,
        scope_workspace_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        effective_role_names = {
            str(role_name or "").strip().lower()
            for role_name in service.get_user_effective_role_names(user_id)
        }
        include_all_workspaces = "super_admin" in effective_role_names
        scope_workspace_value = str(scope_workspace_id or "").strip() or None

        sql = """
            SELECT workspace_id, MAX(is_default) AS is_default
            FROM (
                SELECT
                    wm.workspace_id AS workspace_id,
                    COALESCE(wm.is_default, 0) AS is_default
                FROM workspace_membership wm
                JOIN workspace w
                  ON w.id = wm.workspace_id
                 AND COALESCE(w.is_active, 1) = 1
                WHERE wm.user_id = :user_id
                  AND COALESCE(wm.is_active, 1) = 1
                  AND (:scope_workspace_id IS NULL OR wm.workspace_id = :scope_workspace_id)

                UNION ALL

                SELECT
                    w.id AS workspace_id,
                    0 AS is_default
                FROM organization_membership om
                JOIN organization o
                  ON o.id = om.organization_id
                 AND COALESCE(o.is_active, 1) = 1
                JOIN workspace w
                  ON w.organization_id = om.organization_id
                 AND COALESCE(w.is_active, 1) = 1
                WHERE om.user_id = :user_id
                  AND COALESCE(om.is_active, 1) = 1
                  AND (:scope_workspace_id IS NULL OR w.id = :scope_workspace_id)
        """
        if include_all_workspaces:
            sql += """

                UNION ALL

                SELECT
                    w.id AS workspace_id,
                    0 AS is_default
                FROM workspace w
                WHERE COALESCE(w.is_active, 1) = 1
                  AND (:scope_workspace_id IS NULL OR w.id = :scope_workspace_id)
            """

        sql += """
            ) access_rows
            GROUP BY workspace_id
            ORDER BY is_default DESC, workspace_id ASC
        """
        try:
            result = self._sql.execute_query_mappings(
                sql,
                {"user_id": user_id, "scope_workspace_id": scope_workspace_value},
            )
            rows = [dict(row) for row in result]
            if not rows:
                return []
            has_default = any(bool(row.get("is_default")) for row in rows)
            if not has_default:
                rows[0]["is_default"] = True
                for row in rows[1:]:
                    row["is_default"] = False
            else:
                seen_default = False
                for row in rows:
                    if bool(row.get("is_default")) and not seen_default:
                        row["is_default"] = True
                        seen_default = True
                    else:
                        row["is_default"] = False
            return rows
        except exc.SQLAlchemyError as err:
            logger.error("%s - %s", sql, err)
            raise ForgeError(f"Failed to retrieve user workspaces: {str(err)}", 500) from err

    def user_is_visible_in_workspace(self, user_id: str, workspace_id: str) -> bool:
        rows = self._sql.execute_query_mappings(
            """
            SELECT 1
            FROM workspace_membership wm
            WHERE wm.user_id = :user_id
              AND wm.workspace_id = :workspace_id
              AND COALESCE(wm.is_active, 1) = 1

            UNION ALL

            SELECT 1
            FROM workspace w
            JOIN organization_membership om
              ON om.organization_id = w.organization_id
             AND om.user_id = :user_id
             AND COALESCE(om.is_active, 1) = 1
            WHERE w.id = :workspace_id
              AND COALESCE(w.is_active, 1) = 1
            LIMIT 1
            """,
            {"user_id": str(user_id or "").strip(), "workspace_id": str(workspace_id or "").strip()},
        )
        return bool(rows)

    def get_user_workspaces_bulk(
        self,
        service: "UserService",
        user_ids: List[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        out: Dict[str, List[Dict[str, Any]]] = {}
        for uid in user_ids or []:
            out[str(uid)] = service.get_user_workspaces(str(uid))
        return out

    def delete_user_workspace(self, user_id: str, workspace_id: str) -> Dict[str, str]:
        sql = "DELETE FROM workspace_membership WHERE user_id = :user_id AND workspace_id = :workspace_id"
        try:
            with self._sql.transaction() as tx:
                tx.execute_write(sql, {"user_id": user_id, "workspace_id": workspace_id})
            return {"message": "Mapping deleted successfully"}
        except exc.SQLAlchemyError as err:
            logger.error("%s - %s", sql, err)
            raise ForgeError(f"Failed to map user to workspace: {str(err)}", 500) from err
