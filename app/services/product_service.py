import logging
import uuid
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import exc

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.models.product import Product
from app.models.product_role import ProductRole
from app.models.role import Role
from app.models.status_enum import ProductStatus
from app.ports.sql_executor import SQLExecutor

logger = logging.getLogger(__name__)


class ProductService:
    # Reused status predicate (qualified with alias p)
    _STATUS_WHERE = "( :status = 'All' AND p.status IS NOT NULL ) OR ( p.status = :status )"
    _BASE_PRODUCT_SQL = """                SELECT 
                    p.product_id,
                    p.product_name,
                    p.status,
                    p.last_update,
                    pr.product_role_id,
                    r.role_id,
                    r.role_name
                FROM products p
                LEFT JOIN product_roles pr ON p.product_id = pr.product_id
                LEFT JOIN roles r          ON pr.role_id = r.role_id """

    def __init__(self, *, sql: Optional[SQLExecutor] = None) -> None:
        self._sql = sql or MySQLSQLExecutor()
    
    # ---------- Public API ----------
    def get_counts(self):
        sql = """
            SELECT status, COUNT(*) as count
            FROM products WHERE status is not null
            GROUP BY status
        """

        try:
            results = self._sql.execute_query_mappings(sql)
            counts = {row["status"]: row["count"] for row in results}
            counts["All"] = sum(counts.values())

            for status in ProductStatus:
                counts.setdefault(status.value, 0)

            return counts
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ServiceError(f"Database error: {str(e)}", 500)

    def get_products(
        self,
        status: str = "All",
        cursor: Optional[str] = None,
        limit: int = 10,
        direction: str = "forward",
    ) -> Tuple[List["Product"], Optional[str], Optional[str], int]:
        """
        Cursor-based pagination over products with roles.
        Returns (products, next_cursor, prev_cursor, total_count).
        direction: 'forward' (default) or 'prev'
        """
        if direction not in ("forward", "prev", "backward"):
            direction = "forward"

        try:
            # 1) page by product_id (no joins)
            ids, has_more = self._page_product_ids(status, cursor, limit, direction)

            # 2) total count (status only)
            total_count = self._count_products(status)

            if not ids:
                return [], None, None, total_count

            # normalize final (ASC) order for display
            if direction != "forward":
                ids = list(reversed(ids))

            # 3) compute cursors from final ids
            first_id, last_id = ids[0], ids[-1]
            if direction == "forward":
                prev_cursor = first_id if cursor else None
                next_cursor = last_id if has_more else None
            else:
                prev_cursor = first_id if has_more else None
                next_cursor = last_id

            # 4) fetch & map details
            rows = self._fetch_product_rows(ids)
        except exc.SQLAlchemyError as e:
            logger.error(f"SQL error in get_products: {str(e)}")
            raise ServiceError(f"Failed to retrieve products: {str(e)}", 500)

        products = self._rows_to_products(rows, ids)
        return products, next_cursor, prev_cursor, total_count

    def get_products_by_group(self, product_group_id: str) -> Product:
        try:
            rows = self._fetch_product_rows_by_group(product_group_id)
        except exc.SQLAlchemyError as e:
            logger.error(f"SQL error in get_product: {str(e)}")
            raise ServiceError(f"Database error: {str(e)}", 500)
        
        if not rows:
            return []
        else:
            ids = []
            for row in rows:
                ids.append(row["product_id"])

            products = self._rows_to_products(rows, ids)
            return products
            
    def get_product(self, product_id: str) -> Product:
        """Return a single product with roles."""
        try:
            rows = self._fetch_product_rows([product_id])
        except exc.SQLAlchemyError as e:
            logger.error(f"SQL error in get_product: {str(e)}")
            raise ServiceError(f"Database error: {str(e)}", 500)

        if not rows:
            logger.error(f"Product not found {product_id}")
            raise ServiceError("Product not found", 404)

        products = self._rows_to_products(rows, [product_id])
        return products[0]

    def check_product_name_exists(self, product_name: str, exclude_product_id: Optional[str] = None) -> bool:
        """
        Case-insensitive existence check. Optional exclude for updates.
        """
        where = "LOWER(product_name) = LOWER(:name)"
        params = {"name": product_name}
        if exclude_product_id:
            where += " AND product_id <> :exclude_id"
            params["exclude_id"] = exclude_product_id

        sql = f"SELECT 1 FROM products WHERE {where} LIMIT 1"
        try:
            rows = self._sql.execute_query(sql, params)
            return bool(rows)
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ServiceError(f"Failed to check product name: {str(e)}", 500)

    def create_product(self, product_name: str, product_group_id: Optional[str], role_ids: Optional[List[str]] = []) -> Dict[str, str]:
        if self.check_product_name_exists(product_name):
            logger.error(f"Product with this product name already exists: {product_name}")
            raise ServiceError("Product with this product name already exists", 409)

        sql = "INSERT INTO products (product_id, product_name, last_update) VALUES(:product_id, :product_name, UTC_TIMESTAMP)"
        product_id = str(uuid.uuid4())

        try:
            with self._sql.transaction() as tx:
                tx.execute_write(sql, {"product_id": product_id, "product_name": product_name})

                if product_group_id:
                    pg_sql = "INSERT INTO product_group_map (product_group_map_id, product_group_id, product_id) VALUES (:product_group_map_id, :product_group_id, :product_id)"
                    parms = {"product_group_map_id": str(uuid.uuid4()),
                             "product_group_id": product_group_id,
                             "product_id": product_id
                             }
                    tx.execute_write(pg_sql, parms)

                if role_ids:
                    add_role = "INSERT INTO product_roles (product_role_id, product_id, role_id) VALUES(:product_role_id, :product_id, :role_id)"
                    for role_id in role_ids:
                        tx.execute_write(
                            add_role,
                            {"product_role_id": str(uuid.uuid4()), "product_id": product_id, "role_id": role_id},
                        )
                        logger.info(f"Role: {role_id} added to product: {product_name}")
                
                logger.info(f"Product {product_name} created successfully")
            return {"product_name": product_name, "product_id": product_id}
        except exc.SQLAlchemyError as e:
            logger.error(f"{sql} - {str(e)}")
            raise ServiceError(f"Database error: {str(e)}", 500)



    def update_product(self, product_id: str, update_data: Product) -> Product:
        """
        Updates a product and synchronizes related roles.
        Expects update_data (Pydantic) to optionally include:
        - product_name: str
        - status: str
        - roles: List[ProductRole|dict], where each item carries a role_id (directly or nested)
        """
        # 1) Load current product
        current = self.get_product(product_id)  # raises 404 if not found

        # 2) Prepare scalar updates (exclude nested)
        # Use Pydantic's model_dump(exclude_unset=True) to only include provided fields
        update_fields: Dict[str, Any] = (
            update_data.model_dump(exclude_unset=True)  # type: ignore[attr-defined]
        )
        roles_payload = update_fields.pop("roles", None)  # handle relations separately

        # Disallow updating primary key / client-provided last_update
        update_fields.pop("product_id", None)
        update_fields.pop("last_update", None)

        # Uniqueness check only if name is changing
        new_name = update_fields.get("product_name")
        if new_name is not None and new_name != current.product_name:
            if self.check_product_name_exists(new_name, exclude_product_id=product_id):
                logger.error(f"Product with this product name already exists: {new_name}")
                raise ServiceError("Product with this product name already exists", 409)

        # Build dynamic SET list for scalar columns
        set_clauses: List[str] = []
        params: Dict[str, Any] = {"pid": product_id}
        for field, value in update_fields.items():
            # only write when changed
            if getattr(current, field, None) != value:
                set_clauses.append(f"{field} = :{field}")
                params[field] = value

        # Always bump last_update even if only roles changed
        set_clauses.append("last_update = CURRENT_TIMESTAMP")
        update_sql = f"""
            UPDATE products
            SET {", ".join(set_clauses)}
            WHERE product_id = :pid
        """

        # Role sync SQL
        insert_sql = """
            INSERT INTO product_roles (product_role_id, product_id, role_id)
            VALUES (:prid, :pid, :rid)
        """

        try:
            with self._sql.transaction() as tx:
                # 3) Update scalar fields (and last_update)
                tx.execute_write(update_sql, params)

                # 4) Sync roles if provided (None = leave as-is; [] = remove all)
                if roles_payload is not None:
                    desired_role_ids = self._extract_role_ids(roles_payload)

                    existing_rows = tx.execute_query_mappings(
                        "SELECT product_role_id, role_id FROM product_roles WHERE product_id = :pid",
                        {"pid": product_id},
                    )
                    existing_role_ids = {str(r["role_id"]) for r in existing_rows}

                    to_delete = existing_role_ids - desired_role_ids
                    to_insert = desired_role_ids - existing_role_ids

                    if to_delete:
                        role_ids = list(to_delete)
                        placeholders = ",".join([f":rid{i}" for i in range(len(role_ids))])
                        params_del = {"pid": product_id, **{f"rid{i}": rid for i, rid in enumerate(role_ids)}}
                        tx.execute_write(
                            f"""
                            DELETE FROM product_roles
                            WHERE product_id = :pid AND role_id IN ({placeholders})
                            """,
                            params_del,
                        )

                    if to_insert:
                        tx.execute_write(
                            insert_sql,
                            [{"prid": str(uuid.uuid4()), "pid": product_id, "rid": rid} for rid in to_insert],
                        )

            # 5) Return fresh product with roles
            return self.get_product(product_id)

        except exc.SQLAlchemyError as e:
            logger.error(f"update_product failed for {product_id}: {e}")
            raise ServiceError(f"Failed to update product: {str(e)}", 500)

    def delete(self, product_id: str):
        delete_product = "DELETE FROM products WHERE product_id = :product_id"
        delete_user_product = "DELETE FROM user_product_map WHERE product_id = :product_id" 
        delete_product_group = "DELETE FROM product_group_map WHERE product_id = :product_id"
        param = {"product_id": product_id}
        try:
            with self._sql.transaction() as tx:
                tx.execute_write(delete_user_product, param)
                tx.execute_write(delete_product_group, param)
                result = tx.execute_write(delete_product, param)
                if (result or 0) == 0:
                    logger.error(f"Product not found: {product_id}")
                    raise ServiceError("Product not found", 404)
            return {"message": "Product deleted successfully"}, 200
        except exc.SQLAlchemyError as e:
            logger.error(str(e))
            raise ServiceError(f"Failed to delete product: {str(e)}", 500)

    # ---------- Internals (helpers) ----------

    def _extract_role_ids(self, items: Iterable[Any]) -> Set[str]:
            """
            Accepts list items like:
            - ProductRole objects
            - {"role_id": "..."}
            - {"role": {"role_id": "..."}}
            Returns a set of role_id strings.
            """
            out: Set[str] = set()
            if not items:
                return out

            for it in items:
                rid = None
                if isinstance(it, ProductRole):
                    rid = getattr(getattr(it, "role", None), "role_id", None) or getattr(it, "role_id", None)
                elif isinstance(it, dict):
                    rid = it.get("role_id") or (it.get("role") or {}).get("role_id")
                else:
                    rid = getattr(it, "role_id", None)
                if rid:
                    out.add(str(rid))
            return out

    def _page_product_ids(
        self,
        status: str,
        cursor: Optional[str],
        limit: int,
        direction: str,
    ) -> Tuple[List[str], bool]:
        """Return page of product_ids and has_more flag."""
        where = self._STATUS_WHERE
        params = {"status": status, "limit_plus_one": limit + 1}

        if cursor:
            op = ">" if direction == "forward" else "<"
            where += f" AND p.product_id {op} :cursor"
            params["cursor"] = cursor

        order = "ASC" if direction == "forward" else "DESC"

        ids_sql = f"""
            SELECT p.product_id
            FROM products p
            WHERE {where}
            ORDER BY p.product_id {order}
            LIMIT :limit_plus_one
        """
        rows = self._sql.execute_query_mappings(ids_sql, params)
        ids = [r["product_id"] for r in rows]
        has_more = len(ids) > limit
        if has_more:
            ids = ids[:limit]
        return ids, has_more

    def _count_products(self, status: str) -> int:
        """Return total count filtered by status only."""
        count_sql = f"SELECT COUNT(*) AS cnt FROM products p WHERE {self._STATUS_WHERE}"
        rows = self._sql.execute_query_mappings(count_sql, {"status": status})
        return int((rows[0].get("cnt") if rows else 0) or 0)

    def _fetch_product_rows_by_group(self, group_id: str) -> List[Dict[str, Any]]:
        sql = f"""
                {self._BASE_PRODUCT_SQL}
                LEFT JOIN product_group_map pm on pm.product_id = p.product_id
                WHERE pm.product_group_id = :product_group_id
                ORDER BY p.product_id ASC
                """
        return self._sql.execute_query_mappings(sql, {"product_group_id": group_id})
    
    def _fetch_product_rows(self, ids: List[str]) -> List[Dict[str, Any]]:
        """Fetch joined rows for the given product_ids (may be empty)."""
        if not ids:
            return []
        placeholders = ",".join([f":id{i}" for i in range(len(ids))])
        params = {f"id{i}": pid for i, pid in enumerate(ids)}
        details_sql = f"""
            {self._BASE_PRODUCT_SQL}
            WHERE p.product_id IN ({placeholders})
            ORDER BY p.product_id ASC
            """
        return self._sql.execute_query_mappings(details_sql, params)

    def _rows_to_products(self, rows: List[Dict[str, Any]], ordered_ids: List[str]) -> List[Product]:
        """Group joined rows into Product objects, preserving ordered_ids order."""
        buckets: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            pid = row["product_id"]
            b = buckets.get(pid)
            if b is None:
                b = buckets[pid] = {
                    "product_name": row["product_name"],
                    "status": row.get("status"),
                    "last_update": row.get("last_update"),
                    "roles": [],
                    "_seen": set(),
                }
            prid = row.get("product_role_id")
            if prid and prid not in b["_seen"]:
                b["roles"].append(
                    ProductRole(
                        product_role_id=prid,
                        role=Role(role_id=row.get("role_id"), role_name=row.get("role_name")),
                    )
                )
                b["_seen"].add(prid)

        products: List[Product] = []
        for pid in ordered_ids:
            data = buckets.get(pid, {"product_name": None, "status": None, "last_update": None, "roles": []})
            products.append(
                Product(
                    product_id=pid,
                    product_name=data["product_name"],
                    status=data["status"],
                    last_update=data["last_update"],
                    roles=data["roles"],
                )
            )
        return products
