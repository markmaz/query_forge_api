from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import exc

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.utils.param_guard import validate_params
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)


class RoleService:
    def __init__(self, *, sql: ForgeQueryPort | None = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def get_roles(self) -> list[dict[str, Any]]:
        query = """
            SELECT
                CAST(id AS CHAR) AS role_id,
                name AS role_name,
                display_name,
                description,
                feature_key,
                is_system
            FROM roles
            ORDER BY name
        """
        try:
            rows = self._sql.execute_query_mappings(query)
            return [dict(row) for row in rows]
        except exc.SQLAlchemyError as err:
            logger.error("get_roles failed: %s", err)
            raise ForgeError(f"Failed to retrieve roles: {err}", status_code=500) from err

    @validate_params("role_name")
    def add_role(self, role_name: str) -> dict[str, Any]:
        name = str(role_name or "").strip()
        if not name:
            raise ForgeError("role_name is required", status_code=400)
        if any(str(row.get("role_name") or "").strip() == name for row in self.get_roles()):
            raise ForgeError("Role name already exists", 409, {"role_name": name})

        params = {
            "name": name,
            "display_name": name.replace("_", " ").replace(":", " ").title(),
        }
        query = """
            INSERT INTO roles (name, display_name, is_system)
            VALUES (:name, :display_name, 0)
        """

        try:
            with self._sql.transaction() as tx:
                tx.execute_write(query, params)
            logger.info("Role created role_name=%s", name)
            try:
                return self.get_role(name)
            except ForgeError:
                return {
                    "role_name": name,
                    "display_name": params["display_name"],
                    "description": None,
                    "feature_key": None,
                    "is_system": 0,
                }
        except exc.SQLAlchemyError as err:
            if "Duplicate" in str(err) or "duplicate" in str(err):
                raise ForgeError("Role name already exists", 409, {"role_name": name}) from err
            logger.error("add_role failed: %s", err)
            raise ForgeError(f"Database error: {err}", status_code=500) from err

    @validate_params("role_name")
    def delete_role(self, role_name: str) -> tuple[dict[str, Any], int]:
        params = {"role_name": str(role_name or "").strip()}
        get_role = """
            SELECT CAST(id AS CHAR) AS role_id, name AS role_name, is_system
            FROM roles
            WHERE name = :role_name
            LIMIT 1
        """
        delete_role_row = "DELETE FROM roles WHERE name = :role_name"

        try:
            with self._sql.transaction() as tx:
                rows = tx.execute_query_mappings(get_role, params)
                if not rows:
                    raise ForgeError("Role not found", status_code=404)
                if int(rows[0].get("is_system") or 0) == 1:
                    raise ForgeError("System roles cannot be deleted", status_code=409)
                tx.execute_write(delete_role_row, params)
            return {"message": "Role deleted successfully"}, 200
        except ForgeError:
            raise
        except exc.SQLAlchemyError as err:
            logger.error("delete_role failed role_name=%s error=%s", role_name, err)
            raise ForgeError(f"Database error: {err}", status_code=500) from err

    @validate_params("role_name")
    def get_role(self, role_name: str) -> dict[str, Any]:
        query = """
            SELECT
                CAST(id AS CHAR) AS role_id,
                name AS role_name,
                display_name,
                description,
                feature_key,
                is_system
            FROM roles
            WHERE name = :role_name
            LIMIT 1
        """
        try:
            rows = self._sql.execute_query_mappings(query, {"role_name": str(role_name or "").strip()})
            if not rows:
                raise ForgeError("Role not found", status_code=404)
            return dict(rows[0])
        except ForgeError:
            raise
        except exc.SQLAlchemyError as err:
            logger.error("get_role failed role_name=%s error=%s", role_name, err)
            raise ForgeError(f"Database error: {err}", status_code=500) from err
