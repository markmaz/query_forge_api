from __future__ import annotations

from typing import Any, Tuple

from flask_restx import Resource

from app.features.domains import shared as domain_routes
from app.features.domains.common import qf_domains_ns


@qf_domains_ns.route("/<int:domain_id>/users")
class DomainUsers(Resource):
    @domain_routes.token_required
    @domain_routes.require_admin()
    def get(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            rows = domain_routes.UserDomainReadService().list_domain_users(
                workspace_id=domain_routes.workspace_id(),
                domain_id=domain_id,
            )
            return {"rows": rows}, 200

        return domain_routes.run(handler)

    @domain_routes.token_required
    @domain_routes.require_admin()
    def post(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            body = domain_routes.json_body_dict()
            workspace_id = domain_routes.workspace_id()
            editor_user_id = domain_routes.require_user_id()
            service = domain_routes.DomainUserWriteService()

            if "add" in body or "remove" in body:
                result = service.apply_changes(
                    workspace_id=workspace_id,
                    editor_user_id=editor_user_id,
                    domain_id=domain_id,
                    add=body.get("add") or [],
                    remove=body.get("remove") or [],
                )
                return result, 200

            target_user_id = (body.get("user_id") or "").strip()
            if not target_user_id:
                raise domain_routes.ForgeError("user_id is required", status_code=400)

            result = service.upsert_user(
                workspace_id=workspace_id,
                editor_user_id=editor_user_id,
                domain_id=domain_id,
                tarrequire_user_id=target_user_id,
                can_read=body.get("can_read", True),
                can_edit=body.get("can_edit", False),
            )
            return result, 201

        return domain_routes.run(handler)


@qf_domains_ns.route("/<int:domain_id>/users/<string:tarrequire_user_id>")
class DomainUserById(Resource):
    @domain_routes.token_required
    @domain_routes.require_admin()
    def delete(self, domain_id: int, tarrequire_user_id: str):
        def handler() -> Tuple[Any, int]:
            result = domain_routes.DomainUserWriteService().remove_user(
                workspace_id=domain_routes.workspace_id(),
                editor_user_id=domain_routes.require_user_id(),
                domain_id=domain_id,
                tarrequire_user_id=tarrequire_user_id,
            )
            return result, 200

        return domain_routes.run(handler)
