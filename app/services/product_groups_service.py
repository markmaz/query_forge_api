from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import exc

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.models.product_group import ProductGroup
from app.models.status_enum import ProductGroupStatus
from app.ports.sql_executor import ForgeQueryPort
from app.services.product_service import ProductService

logger = logging.getLogger(__name__)


class ProductGroupService:
    _STATUS_WHERE = "( :status = 'All' AND status IS NOT NULL ) OR ( status = :status )"

    def __init__(self, *, sql: ForgeQueryPort | None = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def get_counts(self) -> dict[str, int]:
        query = "SELECT status, COUNT(*) as count FROM products_groups WHERE status is not null GROUP BY status"
        try:
            rows = self._sql.execute_query_mappings(query)
            counts = {str(row["status"]): int(row["count"]) for row in rows}
            counts["All"] = sum(counts.values())
            for state in ProductGroupStatus:
                counts.setdefault(state.value, 0)
            return counts
        except exc.SQLAlchemyError as err:
            logger.error("%s - %s", query, err)
            raise ForgeError(f"Database error: {err}", status_code=500) from err

    def get_product_groups(self, status: str = "All") -> list[ProductGroup]:
        query = (
            "SELECT product_group_id, product_group_name, status, last_update "
            f"FROM product_groups WHERE {self._STATUS_WHERE}"
        )
        try:
            rows = self._sql.execute_query_mappings(query, {"status": status})
            groups = [ProductGroup(**dict(row)) for row in rows]
            product_service = ProductService(sql=self._sql)
            for group in groups:
                group.products = product_service.get_products_by_group(group.product_group_id)
            return groups
        except exc.SQLAlchemyError as err:
            logger.error("%s - %s", query, err)
            raise ForgeError(f"Database error: {err}", status_code=500) from err

    def create_product_group(self, group_name: str) -> ProductGroup:
        if self._check_product_group(group_name):
            raise ForgeError("Product Group with this name already exists", status_code=409)

        insert_sql = """
            INSERT INTO product_groups
            (product_group_id, product_group_name, status, last_update)
            VALUES(:product_group_id, :product_group_name, :status, CURRENT_TIMESTAMP)
        """
        product_group_id = str(uuid.uuid4())

        try:
            with self._sql.transaction() as tx:
                tx.execute_write(
                    insert_sql,
                    {
                        "status": ProductGroupStatus.ACTIVE.value,
                        "product_group_id": product_group_id,
                        "product_group_name": group_name,
                    },
                )
            return self.get_product_group(product_group_id)
        except exc.SQLAlchemyError as err:
            logger.error("%s - %s", insert_sql, err)
            raise ForgeError(f"Database error: {err}", status_code=500) from err

    def get_product_group(self, product_group_id: str) -> ProductGroup:
        query = (
            "SELECT product_group_id, product_group_name, status, last_update "
            "FROM product_groups WHERE product_group_id = :product_group_id"
        )
        try:
            rows = self._sql.execute_query_mappings(query, {"product_group_id": product_group_id})
            if not rows:
                raise ForgeError(f"Product Group not found: {product_group_id}", status_code=404)

            group = ProductGroup(**dict(rows[0]))
            group.products = ProductService(sql=self._sql).get_products_by_group(product_group_id)
            return group
        except ForgeError:
            raise
        except exc.SQLAlchemyError as err:
            logger.error("%s - %s", query, err)
            raise ForgeError(f"Database error: {err}", status_code=500) from err

    def _check_product_group(self, group_name: str) -> bool:
        query = "SELECT 1 FROM product_groups WHERE product_group_name =:product_group_name LIMIT 1"
        try:
            rows = self._sql.execute_query(query, {"product_group_name": group_name})
            return bool(rows)
        except exc.SQLAlchemyError as err:
            logger.error("%s - %s", query, err)
            raise ForgeError(f"Failed to check product name: {err}", status_code=500) from err

    def delete_product_group(self, product_group_id: str) -> dict[str, int]:
        check_sql = "SELECT 1 FROM product_groups WHERE product_group_id = :id"
        delete_map_sql = "DELETE FROM product_group_map WHERE product_group_id = :id"
        delete_group_sql = "DELETE FROM product_groups WHERE product_group_id = :id"
        params = {"id": product_group_id}

        try:
            with self._sql.transaction() as tx:
                if not tx.execute_query(check_sql, params):
                    raise ForgeError("Product group not found", status_code=404)

                deleted_mappings = tx.execute_write(delete_map_sql, params)
                deleted_group = tx.execute_write(delete_group_sql, params)
                if not deleted_group:
                    raise ForgeError("Product group not found after delete attempt", status_code=404)

                return {
                    "deleted_group": int(deleted_group or 0),
                    "deleted_mappings": int(deleted_mappings or 0),
                }
        except ForgeError:
            raise
        except exc.SQLAlchemyError as err:
            logger.exception("Failed to delete product group %s", product_group_id)
            raise ForgeError(f"Failed to delete product group: {err}", status_code=500) from err

    def add_product_to_group(self, product_id: str, product_group_id: str) -> ProductGroup:
        group = self.get_product_group(product_group_id)
        if not group:
            raise ForgeError("That product group does not exist.", status_code=404)

        if any(product.product_id == product_id for product in group.products):
            return self.get_product_group(product_group_id)

        insert_sql = (
            "INSERT INTO product_group_map (product_group_map_id, product_group_id, product_id) "
            "VALUES(:product_group_map_id, :product_group_id, :product_id)"
        )
        params: dict[str, Any] = {
            "product_group_map_id": str(uuid.uuid4()),
            "product_group_id": product_group_id,
            "product_id": product_id,
        }

        try:
            with self._sql.transaction() as tx:
                tx.execute_write(insert_sql, params)
            return self.get_product_group(product_group_id)
        except exc.SQLAlchemyError as err:
            logger.error("%s - %s", insert_sql, err)
            raise ForgeError(f"Failed to add product: {err}", status_code=500) from err

    def remove_product_from_group(self, product_id: str, product_group_id: str) -> ProductGroup:
        group = self.get_product_group(product_group_id)
        if not group:
            raise ForgeError("That product group does not exist.", status_code=404)

        delete_sql = "DELETE FROM product_group_map WHERE product_group_id = :product_group_id AND product_id = :product_id"
        params = {"product_group_id": product_group_id, "product_id": product_id}

        try:
            with self._sql.transaction() as tx:
                tx.execute_write(delete_sql, params)
            return self.get_product_group(product_group_id)
        except exc.SQLAlchemyError as err:
            logger.error("%s - %s", delete_sql, err)
            raise ForgeError(f"Failed to remove product from product_group: {err}", status_code=500) from err
