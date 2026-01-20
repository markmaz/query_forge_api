import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import exc

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.decorators.validate import validate_params
from app.exceptions.service_error import ServiceError
from app.models.product_role import ProductRole
from app.ports.sql_executor import SQLExecutor

logger = logging.getLogger(__name__)

class RoleService:
    def __init__(self, *, sql: Optional[SQLExecutor] = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

    def get_roles(self) -> List[Dict[str, Any]]:
        """
        Retrieves all roles from the database.
        
        Returns:
            list[dict[str, any]]: Role listing
        Raises:
            ServiceError 404 (Role not found), 500 (database error)
        """
        sql = "SELECT role_id, role_name FROM roles"
        try:
            result = self._sql.execute_query_mappings(sql)
            return [dict(row) for row in result] 
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ServiceError(f"Failed to retrieve users: {str(e)}", 500)
    
    validate_params("role_name")
    def add_role(self, role_name: str) -> Dict[str, Any]:
        """
        Creates a new role
        
        Returns:
            dict[str, any]: Role listing
        Raises:
            ServiceError 409 (Duplicate), 500 (database error)
        """

        existing_roles = self.get_roles()

        if  any(role['role_name'] == role_name for role in existing_roles):
            return ServiceError("Role name already exists", 409, {"role_name": role_name})

        sql = "INSERT INTO roles (role_id, role_name) values (:role_id, :role_name)"
        role_id = str(uuid.uuid4())

        try:
            with self._sql.transaction() as tx:
                tx.execute_write(
                    sql,
                    {"role_id": role_id, "role_name": role_name},
                )
            logger.info(f"Role {role_name} created successfully")
            return {"role_name": role_name,  "role_id": role_id}
        except exc.SQLAlchemyError as e:
            logger.error("Delete role failed: %s", str(e))
            raise ServiceError(f"Database error: {str(e)}", 500)

    validate_params("role_id")
    def delete_role(self, role_id: str) -> Dict[str, Any]:
        """
        Deletes a given role

        :param role_id: The identifier for the role.
        :type role_id: str
        
        Returns:
            
        Raises:
            ServiceError 500 (database error)
        """

        delete_maps = "DELETE FROM user_role_map WHERE role_id = :role_id"
        delete_role = "DELETE FROM roles WHERE role_id = :role_id"

        try:
            with self._sql.transaction() as tx:
                tx.execute_write(delete_maps, {"role_id": role_id})
                logger.info(f"Deleted role: {role_id} from user_role_map")

                tx.execute_write(delete_role, {"role_id": role_id})
                logger.info(f"Delete role: {role_id} from roles")

            return {"message": "Role deleted successfully"}, 200
        except exc.SQLAlchemyError as e:
            logger.error("Delete role failed: %s", str(e))
            raise ServiceError(f"Database error: {str(e)}", 500)
    

    validate_params("role_id")
    def get_role(self, role_id: str) -> Dict[str, Any]:
        """
        Retrieves a given role

        :param role_id: The identifier for the role.
        :type role_id: str
        
        Returns:
            Dict[str, Any]
        Raises:
            ServiceError 404 (Not found), 500 (database error)
        """

        sql = "SELECT role_id, role_name FROM roles WHERE role_id = :role_id"

        try:
            rows = self._sql.execute_query_mappings(sql, {"role_id": role_id})
            result = rows[0] if rows else None
                
            if not result:
                logger.error(f"Role not found: {role_id}")
                raise ServiceError("Role not found", 404)
                
            return dict(result)
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ServiceError(f"Database error: {str(e)}", 500)
        
    validate_params("product_id", "role_id")
    def map_product_to_role(self, product_id: str, role_id: str):

        if not self.has_role(product_id, role_id):
            sql = "INSERT INTO product_roles (product_role_id, product_id, role_id) VALUES(:product_role_id, :product_id, :role_id)"

            try:
                with self._sql.transaction() as tx:
                    product_role_id =  str(uuid.uuid4())
                    tx.execute_write(
                        sql,
                        {"product_role_id": product_role_id, "product_id": product_id, "role_id": role_id},
                    )
                return {"product_role_id": product_role_id, "product_id": product_id, "role_id": role_id}
            except exc.SQLAlchemyError as e:
                logger.error(f"{sql} - {str(e)}")
                raise ServiceError(f"Database error: {str(e)}", 500)
        else:
            raise ServiceError("That role has already been mapped to that product.", 409)

    validate_params("product_id", "role_id")

    def remove_role_from_product(self, product_id: str, role_id: str) -> dict:
        """
        Remove the (product_id, role_id) mapping from product_roles.
        - 404 if the mapping doesn't exist
        - 409 if the mapping is assigned to any users
        - 200 + payload on success
        """
        # 1) Resolve product_role_id from (product_id, role_id)
        select_pr = """
            SELECT product_role_id
            FROM product_roles
            WHERE product_id = :pid AND role_id = :rid
            LIMIT 1
        """

        # 2) Check usage in user_roles
        check_usage = """
            SELECT COUNT(*) AS cnt
            FROM user_roles
            WHERE product_role_id = :prid
        """

        # 3) Delete mapping
        delete_pr = """
            DELETE FROM product_roles
            WHERE product_role_id = :prid
        """

        # 4) Touch product last_update
        touch_product = """
            UPDATE products
            SET last_update = CURRENT_TIMESTAMP
            WHERE product_id = :pid
        """

        try:
            with self._sql.transaction() as tx:
                rows = tx.execute_query_mappings(select_pr, {"pid": product_id, "rid": role_id})
                row = rows[0] if rows else None
                if not row:
                    logger.info("No product_role mapping for product_id=%s role_id=%s", product_id, role_id)
                    raise ServiceError("Role mapping not found for this product.", 404)

                product_role_id = row["product_role_id"]
                params = {"prid": product_role_id}

                usage_rows = tx.execute_query_mappings(check_usage, params)
                in_use = int((usage_rows[0].get("cnt") if usage_rows else 0) or 0)
                if in_use > 0:
                    logger.error("Role mapping %s is in use by %d users", product_role_id, in_use)
                    raise ServiceError(
                        f"That role is in use by {in_use} users. Cannot delete this role from the product.",
                        409
                    )

                res = tx.execute_write(delete_pr, params)
                if (res or 0) == 0:
                    logger.error("Role wasn't found during the delete. Someone else must have deleted it first?")
                    raise ServiceError("Role mapping not found (concurrent update).", 404)

                tx.execute_write(touch_product, {"pid": product_id})

                logger.info("Deleted product_role_id=%s from product_id=%s", product_role_id, product_id)
                return {"ok": True, "deleted_product_role_id": product_role_id}

        except exc.SQLAlchemyError as e:
            logger.error("remove_role_from_product failed: %s", str(e))
            raise ServiceError(f"Database error: {str(e)}", 500)


    @validate_params("product_id", "role_id")
    def has_role(self, product_id: str, role_id: str) -> bool:
        """"
        Returns:
            bool
        Raises:
            ServiceError 409 (Duplicate), 500 (database error)
        """

        sql = "SELECT * from product_roles WHERE product_id = :product_id AND role_id = :role_id"
        try:
            result = self._sql.execute_query(sql, {"role_id": role_id, "product_id": product_id})
            if not result:
                return False
            return True
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ServiceError(f"Database error: {str(e)}", 500)
        
        @validate_params("product_id")
        def get_roles_for_product(self, product_id: str) -> List[ProductRole]:
            #sql = text("SELECT role_name, p.role_id, p.product_role_id")
            pass
