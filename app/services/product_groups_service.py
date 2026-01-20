import logging
import uuid
from typing import Dict, Optional

from sqlalchemy import exc

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.models.product_group import ProductGroup
from app.models.status_enum import ProductGroupStatus
from app.ports.sql_executor import SQLExecutor
from app.services.product_service import ProductService

logger = logging.getLogger(__name__)

class ProductGroupService:
    _STATUS_WHERE = "( :status = 'All' AND status IS NOT NULL ) OR ( status = :status )"

    def __init__(self, *, sql: Optional[SQLExecutor] = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

    def get_counts(self):
        sql = "SELECT status, COUNT(*) as count FROM products_groups WHERE status is not null GROUP BY status"

        try:
            results = self._sql.execute_query_mappings(sql)
            counts = {row["status"]: row["count"] for row in results}
            counts["All"] = sum(counts.values())

            for status in ProductGroupStatus:
                counts.setdefault(status.value, 0)

            return counts
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ServiceError(f"Database error: {str(e)}", 500)
    
    def get_product_groups(self, status: str = "All"):
        sql = f"SELECT product_group_id, product_group_name, status, last_update FROM product_groups WHERE {self._STATUS_WHERE}"
        try:
            results = self._sql.execute_query_mappings(sql, {"status": status})
            pg_list = [ProductGroup(**dict(row)) for row in results]

            service = ProductService(sql=self._sql)
            for pg in pg_list:
                pg.products = service.get_products_by_group(pg.product_group_id)

            return pg_list
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ServiceError(f"Database error: {str(e)}", 500)
    
    
    def create_product_group(self, group_name: str) -> ProductGroup:
        if self._check_product_group(group_name):
            logger.error(f"Product Group with this name already exists: {group_name}")
            raise ServiceError("Product Group with this name already exists", 409)
        
        sql = """
                   INSERT INTO product_groups 
                   (product_group_id, product_group_name, status, last_update) 
                   VALUES(:product_group_id, :product_group_name, :status, CURRENT_TIMESTAMP)
                   """
        
        product_group_id = str(uuid.uuid4())

        try:
            with self._sql.transaction() as tx:
                tx.execute_write(
                    sql,
                    {"status" : ProductGroupStatus.ACTIVE.value, 
                     "product_group_id": product_group_id,
                     "product_group_name": group_name},
                )
                
                logger.info(f"Product Group: {group_name} has been added.")
            return self.get_product_group(product_group_id)
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ServiceError(f"Database error: {str(e)}", 500)
    
    def get_product_group(self, product_group_id:str) -> ProductGroup:
        sql = "SELECT product_group_id, product_group_name, status, last_update FROM product_groups WHERE product_group_id = :product_group_id"
        
        try:
             results = self._sql.execute_query_mappings(sql, {"product_group_id": product_group_id})
             row = results[0] if results else None

             if row:
                product_group = ProductGroup(**dict(row))
                service = ProductService(sql=self._sql)
                product_group.products = service.get_products_by_group(product_group_id)
                return product_group
             raise ServiceError(f"Product Group not found: {product_group_id}", 404)
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ServiceError(f"Database error: {str(e)}", 500)
    
    def _check_product_group(self, group_name: str) -> ProductGroup:
        sql = "SELECT 1 FROM product_groups WHERE product_group_name =:product_group_name LIMIT 1"
        params = {"product_group_name": group_name}
        try:
            rows = self._sql.execute_query(sql, params)
            return bool(rows)
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ServiceError(f"Failed to check product name: {str(e)}", 500)

    def delete_product_group(self, product_group_id: str) -> Dict[str, int]:
            sql_exists   = "SELECT 1 FROM product_groups WHERE product_group_id = :id"
            sql_del_map  = "DELETE FROM product_group_map WHERE product_group_id = :id"
            sql_del_group= "DELETE FROM product_groups WHERE product_group_id = :id"
            params = {"id": product_group_id}

            try:
                # Use a single transaction so either both deletes happen, or neither.
                with self._sql.transaction() as tx:
                    exists_rows = tx.execute_query(sql_exists, params)
                    exists = bool(exists_rows)
                    if not exists:
                        raise ServiceError("Product group not found", 404)

                    map_res = tx.execute_write(sql_del_map, params)
                    grp_res = tx.execute_write(sql_del_group, params)

                    if (grp_res or 0) == 0:
                        # Extremely unlikely if exists==True, but defensive:
                        raise ServiceError("Product group not found after delete attempt", 404)

                    return {
                        "deleted_group": int(grp_res or 0),
                        "deleted_mappings": int(map_res or 0),
                    }

            except ServiceError:
                # bubble up with existing status
                raise
            except exc.SQLAlchemyError as e:
                logger.exception("Failed to delete product group %s", product_group_id)
                raise ServiceError(f"Failed to delete product group: {str(e)}", 500)
            
    def add_product_to_group(self, product_id: str, product_group_id: str) -> ProductGroup:
        pg = self.get_product_group(product_group_id)
        if pg:
            exists = any(p.product_id == product_id for p in pg.products)

            if exists:
                return self.get_product_group(product_group_id)
            else:
                sql = "INSERT INTO product_group_map (product_group_map_id, product_group_id, product_id) VALUES(:product_group_map_id, :product_group_id, :product_id)"
                params = {
                    "product_group_map_id" : str(uuid.uuid4()),
                    "product_group_id": product_group_id,
                    "product_id": product_id
                }

                try:
                    with self._sql.transaction() as tx:
                        tx.execute_write(sql, params)
                    return self.get_product_group(product_group_id)
                except exc.SQLAlchemyError as e:
                    logger.error(f"{sql} - {str(e)}")
                    raise ServiceError(f"Failed to add product: {str(e)}", 500)
        else:
            raise ServiceError("That product group does not exist.", 404)
        
    def remove_product_from_group(self, product_id: str, product_group_id: str) -> ProductGroup:
        pg = self.get_product_group(product_group_id)

        if pg:
            sql = "DELETE FROM product_group_map WHERE product_group_id = :product_group_id AND product_id = :product_id"
            params = {
                "product_group_id": product_group_id,
                "product_id": product_id
            }

            try:
                with self._sql.transaction() as tx:
                    tx.execute_write(sql, params)
                return self.get_product_group(product_group_id)
            except exc.SQLAlchemyError as e:
                    logger.error(f"{sql} - {str(e)}")
                    raise ServiceError(f"Failed to remove product from product_group: {str(e)}", 500)
        else:
            raise ServiceError("That product group does not exist.", 404)
