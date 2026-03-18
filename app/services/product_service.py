from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy.exc import SQLAlchemyError

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.models.tenancy.product import Product
from app.models.tenancy.role import ProductRole
from app.models.tenancy.role import Role
from app.models.tenancy.status_enum import ProductStatus
from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _CursorWindow:
    ids: List[str]
    has_more: bool


class _ProductStore:
    STATUS_WHERE = "( :status = 'All' AND p.status IS NOT NULL ) OR ( p.status = :status )"
    BASE_JOIN_SQL = """
        SELECT
            p.product_id,
            p.product_name,
            p.status,
            p.last_update,
            pr.product_role_id,
            r.role_id,
            r.role_name
        FROM products p
        LEFT JOIN product_roles pr ON p.product_id = pr.product_id
        LEFT JOIN roles r ON pr.role_id = r.role_id
    """

    def __init__(self, *, sql: ForgeQueryPort) -> None:
        self._sql = sql

    def fetch_counts(self) -> List[Dict[str, Any]]:
        return self._sql.execute_query_mappings(
            """
            SELECT status, COUNT(*) AS count
            FROM products
            WHERE status IS NOT NULL
            GROUP BY status
            """
        )

    def check_name_exists(self, *, product_name: str, exclude_product_id: Optional[str]) -> bool:
        where_sql = "LOWER(product_name) = LOWER(:name)"
        params: Dict[str, Any] = {"name": product_name}
        if exclude_product_id:
            where_sql += " AND product_id <> :exclude_id"
            params["exclude_id"] = exclude_product_id

        rows = self._sql.execute_query(f"SELECT 1 FROM products WHERE {where_sql} LIMIT 1", params)
        return bool(rows)

    def page_product_ids(self, *, status: str, cursor: Optional[str], limit: int, direction: str) -> _CursorWindow:
        op = ">" if direction == "forward" else "<"
        order_dir = "ASC" if direction == "forward" else "DESC"

        params: Dict[str, Any] = {
            "status": status,
            "limit_plus_one": int(limit) + 1,
        }

        where_sql = self.STATUS_WHERE
        if cursor:
            where_sql = f"{where_sql} AND p.product_id {op} :cursor"
            params["cursor"] = cursor

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT p.product_id
            FROM products p
            WHERE {where_sql}
            ORDER BY p.product_id {order_dir}
            LIMIT :limit_plus_one
            """,
            params,
        )

        ids = [str(row["product_id"]) for row in rows]
        has_more = len(ids) > int(limit)
        if has_more:
            ids = ids[: int(limit)]

        return _CursorWindow(ids=ids, has_more=has_more)

    def count_products(self, *, status: str) -> int:
        rows = self._sql.execute_query_mappings(
            f"SELECT COUNT(*) AS cnt FROM products p WHERE {self.STATUS_WHERE}",
            {"status": status},
        )
        return int((rows[0].get("cnt") if rows else 0) or 0)

    def fetch_rows(self, *, product_ids: List[str]) -> List[Dict[str, Any]]:
        if not product_ids:
            return []

        placeholders = ",".join(f":id{i}" for i in range(len(product_ids)))
        params = {f"id{i}": product_id for i, product_id in enumerate(product_ids)}

        return self._sql.execute_query_mappings(
            f"""
            {self.BASE_JOIN_SQL}
            WHERE p.product_id IN ({placeholders})
            ORDER BY p.product_id ASC
            """,
            params,
        )

    def fetch_rows_by_group(self, *, product_group_id: str) -> List[Dict[str, Any]]:
        return self._sql.execute_query_mappings(
            f"""
            {self.BASE_JOIN_SQL}
            LEFT JOIN product_group_map pgm ON pgm.product_id = p.product_id
            WHERE pgm.product_group_id = :product_group_id
            ORDER BY p.product_id ASC
            """,
            {"product_group_id": product_group_id},
        )


class ProductService:
    _STATUS_WHERE = _ProductStore.STATUS_WHERE
    _BASE_PRODUCT_SQL = _ProductStore.BASE_JOIN_SQL

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._store = _ProductStore(sql=self._sql)

    @staticmethod
    def _normalize_direction(direction: str) -> str:
        if direction not in {"forward", "prev", "backward"}:
            return "forward"
        if direction == "backward":
            return "prev"
        return direction

    def get_counts(self):
        try:
            rows = self._store.fetch_counts()
        except SQLAlchemyError as exc:
            logger.error("get_counts failed: %s", exc)
            raise ForgeError(f"Database error: {exc}", 500)

        counts = {row["status"]: row["count"] for row in rows}
        counts["All"] = sum(counts.values())
        for status in ProductStatus:
            counts.setdefault(status.value, 0)
        return counts

    def get_products(
        self,
        status: str = "All",
        cursor: Optional[str] = None,
        limit: int = 10,
        direction: str = "forward",
    ) -> Tuple[List[Product], Optional[str], Optional[str], int]:
        direction = self._normalize_direction(direction)

        try:
            ids, has_more = self._page_product_ids(status, cursor, int(limit), direction)
            total_count = self._count_products(status)

            if not ids:
                return [], None, None, total_count

            ids = list(ids)
            if direction != "forward":
                ids.reverse()

            first_id = ids[0]
            last_id = ids[-1]
            if direction == "forward":
                prev_cursor = first_id if cursor else None
                next_cursor = last_id if has_more else None
            else:
                prev_cursor = first_id if has_more else None
                next_cursor = last_id

            rows = self._fetch_product_rows(ids)
            products = self._rows_to_products(rows, ids)
            return products, next_cursor, prev_cursor, total_count
        except SQLAlchemyError as exc:
            logger.error("get_products failed: %s", exc)
            raise ForgeError(f"Failed to retrieve products: {exc}", 500)

    def get_products_by_group(self, product_group_id: str) -> Product:
        try:
            rows = self._fetch_product_rows_by_group(product_group_id)
        except SQLAlchemyError as exc:
            logger.error("get_products_by_group failed: %s", exc)
            raise ForgeError(f"Database error: {exc}", 500)

        if not rows:
            return []

        ids = [str(row["product_id"]) for row in rows]
        return self._rows_to_products(rows, ids)

    def get_product(self, product_id: str) -> Product:
        try:
            rows = self._fetch_product_rows([product_id])
        except SQLAlchemyError as exc:
            logger.error("get_product failed for %s: %s", product_id, exc)
            raise ForgeError(f"Database error: {exc}", 500)

        if not rows:
            logger.error("Product not found %s", product_id)
            raise ForgeError("Product not found", 404)

        return self._rows_to_products(rows, [product_id])[0]

    def check_product_name_exists(self, product_name: str, exclude_product_id: Optional[str] = None) -> bool:
        try:
            return self._store.check_name_exists(product_name=product_name, exclude_product_id=exclude_product_id)
        except SQLAlchemyError as exc:
            logger.error("check_product_name_exists failed: %s", exc)
            raise ForgeError(f"Failed to check product name: {exc}", 500)

    def create_product(
        self,
        product_name: str,
        product_group_id: Optional[str],
        role_ids: Optional[List[str]] = [],
    ) -> Dict[str, str]:
        if self.check_product_name_exists(product_name):
            logger.error("Product with this product name already exists: %s", product_name)
            raise ForgeError("Product with this product name already exists", 409)

        product_id = str(uuid.uuid4())
        product_insert_sql = "INSERT INTO products (product_id, product_name, last_update) VALUES(:product_id, :product_name, UTC_TIMESTAMP)"

        try:
            with self._sql.transaction() as tx:
                tx.execute_write(product_insert_sql, {"product_id": product_id, "product_name": product_name})

                if product_group_id:
                    tx.execute_write(
                        "INSERT INTO product_group_map (product_group_map_id, product_group_id, product_id) VALUES (:product_group_map_id, :product_group_id, :product_id)",
                        {
                            "product_group_map_id": str(uuid.uuid4()),
                            "product_group_id": product_group_id,
                            "product_id": product_id,
                        },
                    )

                for role_id in role_ids or []:
                    tx.execute_write(
                        "INSERT INTO product_roles (product_role_id, product_id, role_id) VALUES(:product_role_id, :product_id, :role_id)",
                        {
                            "product_role_id": str(uuid.uuid4()),
                            "product_id": product_id,
                            "role_id": role_id,
                        },
                    )

            return {"product_name": product_name, "product_id": product_id}
        except SQLAlchemyError as exc:
            logger.error("create_product failed: %s", exc)
            raise ForgeError(f"Database error: {exc}", 500)

    def update_product(self, product_id: str, update_data: Product) -> Product:
        current = self.get_product(product_id)

        payload: Dict[str, Any] = update_data.model_dump(exclude_unset=True)  # type: ignore[attr-defined]
        roles_payload = payload.pop("roles", None)
        payload.pop("product_id", None)
        payload.pop("last_update", None)

        next_name = payload.get("product_name")
        if next_name is not None and next_name != current.product_name:
            if self.check_product_name_exists(next_name, exclude_product_id=product_id):
                logger.error("Product with this product name already exists: %s", next_name)
                raise ForgeError("Product with this product name already exists", 409)

        set_clauses: List[str] = []
        params: Dict[str, Any] = {"pid": product_id}
        for field, value in payload.items():
            if getattr(current, field, None) != value:
                set_clauses.append(f"{field} = :{field}")
                params[field] = value

        set_clauses.append("last_update = CURRENT_TIMESTAMP")

        try:
            with self._sql.transaction() as tx:
                tx.execute_write(
                    f"""
                    UPDATE products
                    SET {", ".join(set_clauses)}
                    WHERE product_id = :pid
                    """,
                    params,
                )

                if roles_payload is not None:
                    desired = self._extract_role_ids(roles_payload)
                    existing_rows = tx.execute_query_mappings(
                        "SELECT product_role_id, role_id FROM product_roles WHERE product_id = :pid",
                        {"pid": product_id},
                    )
                    existing = {str(row["role_id"]) for row in existing_rows}

                    to_delete = existing - desired
                    to_insert = desired - existing

                    if to_delete:
                        role_ids = list(to_delete)
                        placeholders = ",".join(f":rid{i}" for i in range(len(role_ids)))
                        delete_params = {"pid": product_id, **{f"rid{i}": role_id for i, role_id in enumerate(role_ids)}}
                        tx.execute_write(
                            f"""
                            DELETE FROM product_roles
                            WHERE product_id = :pid AND role_id IN ({placeholders})
                            """,
                            delete_params,
                        )

                    if to_insert:
                        tx.execute_write(
                            """
                            INSERT INTO product_roles (product_role_id, product_id, role_id)
                            VALUES (:prid, :pid, :rid)
                            """,
                            [{"prid": str(uuid.uuid4()), "pid": product_id, "rid": role_id} for role_id in to_insert],
                        )

            return self.get_product(product_id)
        except SQLAlchemyError as exc:
            logger.error("update_product failed for %s: %s", product_id, exc)
            raise ForgeError(f"Failed to update product: {exc}", 500)

    def delete(self, product_id: str):
        try:
            with self._sql.transaction() as tx:
                tx.execute_write("DELETE FROM user_product_map WHERE product_id = :product_id", {"product_id": product_id})
                tx.execute_write("DELETE FROM product_group_map WHERE product_id = :product_id", {"product_id": product_id})
                deleted = tx.execute_write("DELETE FROM products WHERE product_id = :product_id", {"product_id": product_id})
                if int(deleted or 0) == 0:
                    logger.error("Product not found: %s", product_id)
                    raise ForgeError("Product not found", 404)
            return {"message": "Product deleted successfully"}, 200
        except SQLAlchemyError as exc:
            logger.error("delete failed for %s: %s", product_id, exc)
            raise ForgeError(f"Failed to delete product: {exc}", 500)

    def _extract_role_ids(self, items: Iterable[Any]) -> Set[str]:
        out: Set[str] = set()
        for item in items or []:
            role_id = None
            if isinstance(item, ProductRole):
                role_id = getattr(getattr(item, "role", None), "role_id", None) or getattr(item, "role_id", None)
            elif isinstance(item, dict):
                role = item.get("role") or {}
                role_id = item.get("role_id") or role.get("role_id")
            else:
                role_id = getattr(item, "role_id", None)
            if role_id:
                out.add(str(role_id))
        return out

    def _page_product_ids(
        self,
        status: str,
        cursor: Optional[str],
        limit: int,
        direction: str,
    ) -> Tuple[List[str], bool]:
        window = self._store.page_product_ids(
            status=status,
            cursor=cursor,
            limit=int(limit),
            direction="forward" if direction == "forward" else "prev",
        )
        return window.ids, window.has_more

    def _count_products(self, status: str) -> int:
        return self._store.count_products(status=status)

    def _fetch_product_rows_by_group(self, group_id: str) -> List[Dict[str, Any]]:
        return self._store.fetch_rows_by_group(product_group_id=group_id)

    def _fetch_product_rows(self, ids: List[str]) -> List[Dict[str, Any]]:
        return self._store.fetch_rows(product_ids=ids)

    def _rows_to_products(self, rows: List[Dict[str, Any]], ordered_ids: List[str]) -> List[Product]:
        grouped: Dict[str, Dict[str, Any]] = {}

        for row in rows:
            product_id = str(row["product_id"])
            slot = grouped.setdefault(
                product_id,
                {
                    "product_name": row.get("product_name"),
                    "status": row.get("status"),
                    "last_update": row.get("last_update"),
                    "roles": [],
                    "seen_role_keys": set(),
                },
            )

            product_role_id = row.get("product_role_id")
            if not product_role_id or product_role_id in slot["seen_role_keys"]:
                continue

            role_id = row.get("role_id")
            role_name = row.get("role_name")
            if role_id is None:
                continue

            slot["roles"].append(
                ProductRole(
                    product_role_id=str(product_role_id),
                    role=Role(role_id=str(role_id), role_name=str(role_name or "")),
                )
            )
            slot["seen_role_keys"].add(product_role_id)

        products: List[Product] = []
        for product_id in ordered_ids:
            base = grouped.get(
                product_id,
                {
                    "product_name": None,
                    "status": None,
                    "last_update": None,
                    "roles": [],
                },
            )
            products.append(
                Product(
                    product_id=product_id,
                    product_name=base.get("product_name"),
                    status=base.get("status"),
                    last_update=base.get("last_update"),
                    roles=list(base.get("roles") or []),
                )
            )

        return products
