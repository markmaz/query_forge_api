from __future__ import annotations

from typing import Any, Tuple

from flask_restx import Resource

from app.features.domains import shared as domain_routes
from app.features.domains.common import qf_domains_ns


@qf_domains_ns.route("/column-sample")
class ColumnSample(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog")
    def get(self):
        def handler() -> Tuple[Any, int]:
            workspace_table_id = (domain_routes.request.args.get("workspace_table_id") or "").strip()
            if not workspace_table_id:
                raise domain_routes.ForgeError("workspace_table_id is required", status_code=400)

            column_name = (domain_routes.request.args.get("column_name") or "").strip()
            if not column_name:
                raise domain_routes.ForgeError("column_name is required", status_code=400)

            payload = domain_routes.DomainColumnSampleReadService().sample_column_values(
                workspace_id=domain_routes.workspace_id(),
                user_id=domain_routes.require_user_id(),
                workspace_table_id=int(workspace_table_id),
                column_name=column_name,
                limit=domain_routes.int_arg("limit", default=10),
            )
            return payload, 200

        return domain_routes.run(handler, log_message="Column sample failed", client_error="Column sample failed")


@qf_domains_ns.route("/workspace-tables")
class WorkspaceTables(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog")
    def get(self):
        def handler() -> Tuple[Any, int]:
            rows = domain_routes.DomainTableReadService().list_workspace_tables(
                workspace_id=domain_routes.workspace_id(),
                q=(domain_routes.request.args.get("q") or "").strip() or None,
                schema_name=(domain_routes.request.args.get("schema_name") or "").strip() or None,
                catalog_name=(domain_routes.request.args.get("catalog_name") or "").strip() or None,
                only_exists_in_dbx=domain_routes.bool_arg("only_exists_in_dbx", default=True),
                limit=domain_routes.int_arg("limit", default=500),
                offset=domain_routes.int_arg("offset", default=0),
                mapped=domain_routes.bool_arg("mapped", default=None),
            )
            return {"rows": rows}, 200

        return domain_routes.run(
            handler,
            log_message="Workspace tables fetch failed",
            client_error="Workspace tables fetch failed",
        )


@qf_domains_ns.route("/<int:domain_id>/tables")
class DomainTables(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog")
    def get(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            rows = domain_routes.DomainTableReadService().list_domain_tables(
                workspace_id=domain_routes.workspace_id(),
                domain_id=domain_id,
            )
            return {"rows": rows}, 200

        return domain_routes.run(
            handler,
            log_message=f"Domain tables fetch failed domain_id={domain_id}",
            client_error="Domain tables fetch failed",
        )

    @domain_routes.token_required
    @domain_routes.require_access("catalog", role="admin")
    def post(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            body = domain_routes.json_body_dict()
            service = domain_routes.DomainTableWriteService()
            workspace_id = domain_routes.workspace_id()
            user_id = domain_routes.require_user_id()

            if "workspaceTableId" in body:
                workspace_table_id = body.get("workspaceTableId")
                if workspace_table_id is None:
                    raise domain_routes.ForgeError("workspaceTableId is required", status_code=400)

                row = service.add_or_update_table(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    domain_id=domain_id,
                    workspace_table_id=int(workspace_table_id),
                    relation_kind=body.get("relationKind"),
                    relation_kind_set="relationKind" in body,
                    role=body.get("role"),
                    role_set="role" in body,
                    sort_order=body.get("sortOrder"),
                    sort_order_set="sortOrder" in body,
                    table_alias=body.get("tableAlias"),
                    table_alias_set="tableAlias" in body,
                    filter_mode=body.get("filterMode"),
                    filter_mode_set="filterMode" in body,
                    cardinality=body.get("cardinality"),
                    cardinality_set="cardinality" in body,
                )
                return {"rows": [row]}, 200

            res = service.apply_changes(
                workspace_id=workspace_id,
                user_id=user_id,
                domain_id=domain_id,
                add=body.get("add"),
                remove=body.get("remove"),
            )
            return res, 200

        return domain_routes.run(
            handler,
            log_message=f"Domain tables update failed domain_id={domain_id}",
            client_error="Domain tables update failed",
        )


@qf_domains_ns.route("/<int:domain_id>/tables/<int:workspace_table_id>/primary")
class DomainPrimaryTable(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog", role="admin")
    def patch(self, domain_id: int, workspace_table_id: int):
        def handler() -> Tuple[Any, int]:
            payload = domain_routes.json_body_dict()
            if payload.get("isPrimary") is not True:
                raise domain_routes.ForgeError("isPrimary must be true", status_code=400)

            rows = domain_routes.DomainJoinService().set_primary_table(
                workspace_id=domain_routes.workspace_id(),
                domain_id=domain_id,
                workspace_table_id=workspace_table_id,
            )
            return {"rows": rows}, 200

        return domain_routes.run(
            handler,
            log_message=f"Domain primary table update failed domain_id={domain_id}",
            client_error="Domain primary table update failed",
        )


@qf_domains_ns.route("/<int:domain_id>/joins")
class DomainJoins(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog")
    def get(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            rows = domain_routes.DomainJoinService().list_domain_joins(
                workspace_id=domain_routes.workspace_id(),
                domain_id=domain_id,
            )
            return {"rows": rows}, 200

        return domain_routes.run(
            handler,
            log_message=f"Domain joins fetch failed domain_id={domain_id}",
            client_error="Domain joins fetch failed",
        )

    @domain_routes.token_required
    @domain_routes.require_access("catalog", role="admin")
    def post(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            payload = domain_routes.json_body_dict()
            from_id = payload.get("fromWorkspaceTableId")
            to_id = payload.get("toWorkspaceTableId")
            if from_id is None or to_id is None:
                raise domain_routes.ForgeError("fromWorkspaceTableId and toWorkspaceTableId are required", status_code=400)

            result = domain_routes.DomainJoinService().create_join(
                workspace_id=domain_routes.workspace_id(),
                domain_id=domain_id,
                from_workspace_table_id=int(from_id),
                to_workspace_table_id=int(to_id),
                join_type=str(payload.get("joinType") or "LEFT").upper(),
                join_spec=payload.get("joinSpec") or {},
                sort_order=int(payload.get("sortOrder") or 0),
            )
            return result, 200

        return domain_routes.run(
            handler,
            log_message=f"Domain join create failed domain_id={domain_id}",
            client_error="Domain join create failed",
        )


@qf_domains_ns.route("/<int:domain_id>/joins/<string:join_id>")
class DomainJoin(Resource):
    @domain_routes.token_required
    @domain_routes.require_access("catalog", role="admin")
    def patch(self, domain_id: int, join_id: str):
        def handler() -> Tuple[Any, int]:
            payload = domain_routes.json_body_dict()
            from_id = payload.get("fromWorkspaceTableId")
            to_id = payload.get("toWorkspaceTableId")
            if from_id is None or to_id is None:
                raise domain_routes.ForgeError("fromWorkspaceTableId and toWorkspaceTableId are required", status_code=400)

            result = domain_routes.DomainJoinService().update_join(
                workspace_id=domain_routes.workspace_id(),
                domain_id=domain_id,
                join_id=join_id,
                from_workspace_table_id=int(from_id),
                to_workspace_table_id=int(to_id),
                join_type=str(payload.get("joinType") or "LEFT").upper(),
                join_spec=payload.get("joinSpec") or {},
                sort_order=int(payload.get("sortOrder") or 0),
            )
            return result, 200

        return domain_routes.run(
            handler,
            log_message=f"Domain join update failed domain_id={domain_id} join_id={join_id}",
            client_error="Domain join update failed",
        )

    @domain_routes.token_required
    @domain_routes.require_access("catalog", role="admin")
    def delete(self, domain_id: int, join_id: str):
        def handler() -> Tuple[Any, int]:
            result = domain_routes.DomainJoinService().delete_join(
                workspace_id=domain_routes.workspace_id(),
                domain_id=domain_id,
                join_id=join_id,
            )
            return result, 200

        return domain_routes.run(
            handler,
            log_message=f"Domain join delete failed domain_id={domain_id} join_id={join_id}",
            client_error="Domain join delete failed",
        )
