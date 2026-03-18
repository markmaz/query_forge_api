from __future__ import annotations

from typing import Any

from flask import jsonify, request
from flask_restx import Namespace, reqparse
from app.routes.forge_resource import ForgeResource

from app.decorators.security import token_required
from app.models.tenancy.product import Product
from app.services.product_service import ProductService
from app.services.role_service import RoleService

product_ns = Namespace("products", description="A product available in Workboard")

_product_query = reqparse.RequestParser()
_product_query.add_argument("status", type=str, default="All", help="Filter by status", location="args")
_product_query.add_argument("cursor", type=str, help="Cursor for pagination", location="args")
_product_query.add_argument("limit", type=int, default=10, help="Number of records per page", location="args")
_product_query.add_argument(
    "direction",
    type=str,
    default="forward",
    choices=["forward", "backward"],
    help="Pagination direction",
    location="args",
)


def _product_service() -> ProductService:
    return ProductService()


def _role_service() -> RoleService:
    return RoleService()


@product_ns.route("/")
class ProductList(ForgeResource):
    @token_required
    def get(self):
        args = _product_query.parse_args()
        products, next_cursor, prev_cursor, total_count = _product_service().get_products(
            status=args["status"],
            cursor=args["cursor"],
            limit=args["limit"],
            direction=args["direction"],
        )
        return {
            "products": [product.model_dump(mode="json") for product in products],
            "next_cursor": next_cursor,
            "prev_cursor": prev_cursor,
            "total_count": total_count,
        }, 200

    @token_required
    def post(self):
        data = request.get_json(silent=True) or {}
        return _product_service().create_product(
            data.get("product_name"),
            data.get("product_group_id"),
            data.get("role_ids"),
        )


@product_ns.route("/counts")
class ProductCounts(ForgeResource):
    def get(self):
        return _product_service().get_counts(), 200


@product_ns.route("/<string:product_id>")
class ProductStandard(ForgeResource):
    @token_required
    def get(self, product_id: str):
        return _product_service().get_product(product_id).model_dump(mode="json")

    @token_required
    def delete(self, product_id: str):
        return _product_service().delete(product_id)

    @token_required
    def put(self, product_id: str):
        payload: dict[str, Any] = request.get_json(force=True) or {}
        updated = _product_service().update_product(product_id, Product(**payload))
        return jsonify(updated.model_dump(mode="json"))


@product_ns.route("/<string:product_id>/roles")
class ProductRoles(ForgeResource):
    @token_required
    def get(self, product_id: str):
        del product_id
        return None

    @token_required
    def put(self, product_id: str):
        data = request.get_json(silent=True) or {}
        return _role_service().map_product_to_role(
            product_id=product_id,
            role_id=data.get("role_id"),
        )


@product_ns.route("/<string:product_id>/roles/<string:role_id>")
class DeleteProductRoles(ForgeResource):
    @token_required
    def delete(self, product_id: str, role_id: str):
        return _role_service().remove_role_from_product(product_id, role_id=role_id)

