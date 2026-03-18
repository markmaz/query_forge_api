from __future__ import annotations

from typing import Any, Dict, List, Optional

from flask import request
from flask_restx import Namespace
from app.routes.forge_resource import ForgeResource

from app.decorators.security import token_required
from app.decorators.rbac import require_access
from app.exceptions.forge_error import ForgeError
from app.services.product_groups_service import ProductGroupService

product_group_ns = Namespace("product-groups", "A collection of products")


def _bool_like_direction(value: Optional[str]) -> str:
    direction = (value or "forward").strip().lower()
    return direction if direction in {"forward", "backward"} else "forward"


def _int_arg(name: str, default: int) -> int:
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except ValueError:
        raise ForgeError(f"Invalid integer for '{name}'", status_code=400)


def _safe_body_dict() -> Dict[str, Any]:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        raise ForgeError("Invalid JSON body", status_code=400)
    return payload


def _to_json_rows(items: List[Any]) -> List[Dict[str, Any]]:
    return [item.model_dump(mode="json") for item in items]


@product_group_ns.route("/")
class ProductGroupList(ForgeResource):
    @token_required
    @require_access("catalog")
    def get(self):
        status = (request.args.get("status") or "All").strip() or "All"
        # Keep parser-compatible args available for future service expansion.
        _ = request.args.get("cursor")
        _ = _int_arg("limit", 10)
        _ = _bool_like_direction(request.args.get("direction"))

        service = ProductGroupService()
        groups = service.get_product_groups(status=status)
        return _to_json_rows(groups)

    @token_required
    @require_access("catalog", role="admin")
    def post(self):
        service = ProductGroupService()
        payload = _safe_body_dict()
        group_name = payload.get("product_group_name")
        if not group_name:
            raise ForgeError("product_group_name is required", status_code=400)

        created = service.create_product_group(group_name)
        return created.model_dump(mode="json")


@product_group_ns.route("/<string:product_group_id>")
class ProductGroupStandard(ForgeResource):
    @token_required
    @require_access("catalog")
    def get(self, product_group_id: str):
        service = ProductGroupService()
        product_group = service.get_product_group(product_group_id)
        return product_group.model_dump(mode="json")

    @token_required
    @require_access("catalog", role="admin")
    def delete(self, product_group_id: str):
        service = ProductGroupService()
        return service.delete_product_group(product_group_id)


@product_group_ns.route("/<string:product_group_id>/products/<string:product_id>")
class ProductGroupMembership(ForgeResource):
    @token_required
    @require_access("catalog", role="admin")
    def put(self, product_group_id: str, product_id: str):
        service = ProductGroupService()
        mapped = service.add_product_to_group(product_id, product_group_id)
        return mapped.model_dump(mode="json")

    @token_required
    @require_access("catalog", role="admin")
    def delete(self, product_group_id: str, product_id: str):
        service = ProductGroupService()
        removed = service.remove_product_from_group(product_id, product_group_id)
        return removed.model_dump(mode="json")
