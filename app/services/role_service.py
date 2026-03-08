from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import exc

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.decorators.validate import validate_params
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)


class RoleService:
    def __init__(self, *, sql: ForgeQueryPort | None = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def get_roles(self) -> list[dict[str, Any]]:
        query = "SELECT role_id, role_name FROM roles"
        try:
            rows = self._sql.execute_query_mappings(query)
            return [dict(row) for row in rows]
        except exc.SQLAlchemyError as err:
            logger.error("%s - %s", query, err)
            raise ForgeError(f"Failed to retrieve users: {err}", status_code=500) from err

    @validate_params("role_name")
    def add_role(self, role_name: str) -> dict[str, Any] | ForgeError:
        if any((row.get("role_name") == role_name) for row in self.get_roles()):
            return ForgeError("Role name already exists", 409, {"role_name": role_name})

        query = "INSERT INTO roles (role_id, role_name) values (:role_id, :role_name)"
        role_id = str(uuid.uuid4())
        params = {"role_id": role_id, "role_name": role_name}

        try:
            with self._sql.transaction() as tx:
                tx.execute_write(query, params)
            logger.info("Role created role_id=%s role_name=%s", role_id, role_name)
            return {"role_name": role_name, "role_id": role_id}
        except exc.SQLAlchemyError as err:
            logger.error("add_role failed: %s", err)
            raise ForgeError(f"Database error: {err}", status_code=500) from err

    @validate_params("role_id")
    def delete_role(self, role_id: str) -> tuple[dict[str, Any], int]:
        delete_user_role_map = "DELETE FROM user_role_map WHERE role_id = :role_id"
        delete_role_row = "DELETE FROM roles WHERE role_id = :role_id"
        params = {"role_id": role_id}

        try:
            with self._sql.transaction() as tx:
                tx.execute_write(delete_user_role_map, params)
                tx.execute_write(delete_role_row, params)
            return {"message": "Role deleted successfully"}, 200
        except exc.SQLAlchemyError as err:
            logger.error("delete_role failed role_id=%s error=%s", role_id, err)
            raise ForgeError(f"Database error: {err}", status_code=500) from err

    @validate_params("role_id")
    def get_role(self, role_id: str) -> dict[str, Any]:
        query = "SELECT role_id, role_name FROM roles WHERE role_id = :role_id"
        try:
            rows = self._sql.execute_query_mappings(query, {"role_id": role_id})
            if not rows:
                raise ForgeError("Role not found", status_code=404)
            return dict(rows[0])
        except ForgeError:
            raise
        except exc.SQLAlchemyError as err:
            logger.error("%s - %s", query, err)
            raise ForgeError(f"Database error: {err}", status_code=500) from err

    @validate_params("product_id", "role_id")
    def map_product_to_role(self, product_id: str, role_id: str) -> dict[str, Any]:
        if self.has_role(product_id, role_id):
            raise ForgeError("That role has already been mapped to that product.", status_code=409)

        insert_query = (
            "INSERT INTO product_roles (product_role_id, product_id, role_id) "
            "VALUES(:product_role_id, :product_id, :role_id)"
        )
        product_role_id = str(uuid.uuid4())
        params = {"product_role_id": product_role_id, "product_id": product_id, "role_id": role_id}

        try:
            with self._sql.transaction() as tx:
                tx.execute_write(insert_query, params)
            return params
        except exc.SQLAlchemyError as err:
            logger.error("%s - %s", insert_query, err)
            raise ForgeError(f"Database error: {err}", status_code=500) from err

    @validate_params("product_id", "role_id")
    def remove_role_from_product(self, product_id: str, role_id: str) -> dict[str, Any]:
        select_mapping = """
            SELECT product_role_id
            FROM product_roles
            WHERE product_id = :pid AND role_id = :rid
            LIMIT 1
        """
        check_usage = """
            SELECT COUNT(*) AS cnt
            FROM user_roles
            WHERE product_role_id = :prid
        """
        delete_mapping = """
            DELETE FROM product_roles
            WHERE product_role_id = :prid
        """
        touch_product = """
            UPDATE products
            SET last_update = CURRENT_TIMESTAMP
            WHERE product_id = :pid
        """

        try:
            with self._sql.transaction() as tx:
                row = (tx.execute_query_mappings(select_mapping, {"pid": product_id, "rid": role_id}) or [None])[0]
                if not row:
                    raise ForgeError("Role mapping not found for this product.", status_code=404)

                product_role_id = row["product_role_id"]
                usage_row = (tx.execute_query_mappings(check_usage, {"prid": product_role_id}) or [{}])[0]
                in_use = int((usage_row.get("cnt") or 0))
                if in_use > 0:
                    raise ForgeError(
                        f"That role is in use by {in_use} users. Cannot delete this role from the product.",
                        status_code=409,
                    )

                deleted = tx.execute_write(delete_mapping, {"prid": product_role_id})
                if not deleted:
                    raise ForgeError("Role mapping not found (concurrent update).", status_code=404)

                tx.execute_write(touch_product, {"pid": product_id})
                return {"ok": True, "deleted_product_role_id": product_role_id}
        except ForgeError:
            raise
        except exc.SQLAlchemyError as err:
            logger.error("remove_role_from_product failed: %s", err)
            raise ForgeError(f"Database error: {err}", status_code=500) from err

    @validate_params("product_id", "role_id")
    def has_role(self, product_id: str, role_id: str) -> bool:
        query = "SELECT * from product_roles WHERE product_id = :product_id AND role_id = :role_id"
        try:
            return bool(self._sql.execute_query(query, {"role_id": role_id, "product_id": product_id}))
        except exc.SQLAlchemyError as err:
            logger.error("%s - %s", query, err)
            raise ForgeError(f"Database error: {err}", status_code=500) from err
