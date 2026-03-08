from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Tuple

from flask import request
from flask_restx import Namespace
from app.routes.forge_resource import ForgeResource

from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import require_user_id
from app.services.domain.builder_column_feed_service import BuilderColumnFeedService, BuilderFeedQuery
from app.services.domain.domain_admin_write_service import DomainAdminWriteService
from app.services.domain.domain_column_sample_read_service import DomainColumnSampleReadService
from app.services.domain.domain_join_service import DomainJoinService
from app.services.domain.domain_summary_read_service import DomainSummaryReadService
from app.services.domain.domain_table_read_service import DomainTableReadService
from app.services.domain.domain_table_write_service import DomainTableWriteService
from app.services.domain.domain_user_read_service import UserDomainReadService
from app.services.domain.domain_user_write_service import DomainUserWriteService
from app.services.domains.capabilities_service import DomainCapabilitiesService

logger = logging.getLogger(__name__)
qf_domains_ns = Namespace("domains", description="Domains + Builder feed + permissions")


def _workspace_id() -> str:
    workspace_id = (request.headers.get("X-Workspace-Id") or "").strip()
    if not workspace_id:
        raise ForgeError("Missing X-Workspace-Id header", status_code=400)
    return workspace_id


def _json_body_dict() -> Dict[str, Any]:
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise ForgeError("Invalid JSON body", status_code=400)
    return body


def _int_arg(name: str, default: int) -> int:
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except ValueError:
        raise ForgeError(f"Invalid integer for '{name}'", status_code=400)


def _bool_arg(name: str, default: Optional[bool] = None) -> Optional[bool]:
    raw = (request.args.get(name) or "").strip().lower()
    if raw == "":
        return default
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    raise ForgeError(f"Invalid boolean for '{name}'", status_code=400)


def _handle_service_error(error: ForgeError):
    return {"error": str(error)}, getattr(error, "status_code", 400) or 400


def _run(handler: Callable[[], Tuple[Any, int]], *, log_message: str, client_error: str):
    try:
        return handler()
    except ForgeError as error:
        return _handle_service_error(error)
    except Exception:
        logger.exception(log_message)
        return {"error": client_error}, 500


@qf_domains_ns.route("/")
class DomainsRoot(ForgeResource):
    @token_required
    def get(self):
        def handler() -> Tuple[Any, int]:
            rows = UserDomainReadService().list_user_domains(
                workspace_id=_workspace_id(),
                user_id=require_user_id(),
            )
            return {"rows": rows}, 200

        return _run(handler, log_message="Domains fetch failed", client_error="Domains fetch failed")

    @token_required
    def post(self):
        def handler() -> Tuple[Any, int]:
            workspace_id = _workspace_id()
            body = _json_body_dict()
            row = DomainAdminWriteService().create_domain(
                workspace_id=workspace_id,
                user_id=require_user_id(),
                name=(body.get("name") or "").strip(),
                kind=body.get("kind"),
                description=body.get("description"),
                model_table_id=body.get("model_table_id"),
                column_name_policy=body.get("column_name_policy"),
            )
            return {"row": row}, 201

        return _run(handler, log_message="Domain create failed", client_error="Domain create failed")


@qf_domains_ns.route("/<int:domain_id>")
class DomainById(ForgeResource):
    @token_required
    def patch(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            body = _json_body_dict()
            row = DomainAdminWriteService().patch_domain(
                workspace_id=_workspace_id(),
                user_id=require_user_id(),
                domain_id=domain_id,
                name=body.get("name") if "name" in body else None,
                kind=body.get("kind") if "kind" in body else None,
                description=body.get("description") if "description" in body else None,
                is_active=body.get("is_active") if "is_active" in body else None,
                model_table_id=body.get("model_table_id") if "model_table_id" in body else None,
                column_name_policy=body.get("column_name_policy") if "column_name_policy" in body else None,
            )
            return {"row": row}, 200

        return _run(
            handler,
            log_message=f"Domain patch failed id={domain_id}",
            client_error="Domain patch failed",
        )

    @token_required
    def delete(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            res = DomainAdminWriteService().delete_domain(
                workspace_id=_workspace_id(),
                user_id=require_user_id(),
                domain_id=domain_id,
            )
            return res, 200

        return _run(
            handler,
            log_message=f"Domain delete failed id={domain_id}",
            client_error="Domain delete failed",
        )


@qf_domains_ns.route("/column-sample")
class ColumnSample(ForgeResource):
    @token_required
    def get(self):
        def handler() -> Tuple[Any, int]:
            workspace_table_id = (request.args.get("workspace_table_id") or "").strip()
            if not workspace_table_id:
                raise ForgeError("workspace_table_id is required", status_code=400)

            column_name = (request.args.get("column_name") or "").strip()
            if not column_name:
                raise ForgeError("column_name is required", status_code=400)

            payload = DomainColumnSampleReadService().sample_column_values(
                workspace_id=_workspace_id(),
                user_id=require_user_id(),
                workspace_table_id=int(workspace_table_id),
                column_name=column_name,
                limit=_int_arg("limit", default=10),
            )
            return payload, 200

        return _run(handler, log_message="Column sample failed", client_error="Column sample failed")


@qf_domains_ns.route("/workspace-tables")
class WorkspaceTables(ForgeResource):
    @token_required
    def get(self):
        def handler() -> Tuple[Any, int]:
            rows = DomainTableReadService().list_workspace_tables(
                workspace_id=_workspace_id(),
                q=(request.args.get("q") or "").strip() or None,
                schema_name=(request.args.get("schema_name") or "").strip() or None,
                catalog_name=(request.args.get("catalog_name") or "").strip() or None,
                only_exists_in_dbx=_bool_arg("only_exists_in_dbx", default=True),
                limit=_int_arg("limit", default=500),
                offset=_int_arg("offset", default=0),
                mapped=_bool_arg("mapped", default=None),
            )
            return {"rows": rows}, 200

        return _run(handler, log_message="Workspace tables fetch failed", client_error="Workspace tables fetch failed")


@qf_domains_ns.route("/<int:domain_id>/tables")
class DomainTables(ForgeResource):
    @token_required
    def get(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            rows = DomainTableReadService().list_domain_tables(
                workspace_id=_workspace_id(),
                domain_id=domain_id,
            )
            return {"rows": rows}, 200

        return _run(
            handler,
            log_message=f"Domain tables fetch failed domain_id={domain_id}",
            client_error="Domain tables fetch failed",
        )

    @token_required
    def post(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            body = _json_body_dict()
            service = DomainTableWriteService()
            workspace_id = _workspace_id()
            user_id = require_user_id()

            if "workspaceTableId" in body:
                workspace_table_id = body.get("workspaceTableId")
                if workspace_table_id is None:
                    raise ForgeError("workspaceTableId is required", status_code=400)

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

        return _run(
            handler,
            log_message=f"Domain tables update failed domain_id={domain_id}",
            client_error="Domain tables update failed",
        )


@qf_domains_ns.route("/<int:domain_id>/tables/<int:workspace_table_id>/primary")
class DomainPrimaryTable(ForgeResource):
    @token_required
    def patch(self, domain_id: int, workspace_table_id: int):
        def handler() -> Tuple[Any, int]:
            payload = _json_body_dict()
            if payload.get("isPrimary") is not True:
                raise ForgeError("isPrimary must be true", status_code=400)

            rows = DomainJoinService().set_primary_table(
                workspace_id=_workspace_id(),
                domain_id=domain_id,
                workspace_table_id=workspace_table_id,
            )
            return {"rows": rows}, 200

        return _run(
            handler,
            log_message=f"Domain primary table update failed domain_id={domain_id}",
            client_error="Domain primary table update failed",
        )


@qf_domains_ns.route("/<int:domain_id>/joins")
class DomainJoins(ForgeResource):
    @token_required
    def get(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            rows = DomainJoinService().list_domain_joins(
                workspace_id=_workspace_id(),
                domain_id=domain_id,
            )
            return {"rows": rows}, 200

        return _run(
            handler,
            log_message=f"Domain joins fetch failed domain_id={domain_id}",
            client_error="Domain joins fetch failed",
        )

    @token_required
    def post(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            payload = _json_body_dict()
            from_id = payload.get("fromWorkspaceTableId")
            to_id = payload.get("toWorkspaceTableId")
            if from_id is None or to_id is None:
                raise ForgeError("fromWorkspaceTableId and toWorkspaceTableId are required", status_code=400)

            result = DomainJoinService().create_join(
                workspace_id=_workspace_id(),
                domain_id=domain_id,
                from_workspace_table_id=int(from_id),
                to_workspace_table_id=int(to_id),
                join_type=str(payload.get("joinType") or "LEFT").upper(),
                join_spec=payload.get("joinSpec") or {},
                sort_order=int(payload.get("sortOrder") or 0),
            )
            return result, 200

        return _run(
            handler,
            log_message=f"Domain join create failed domain_id={domain_id}",
            client_error="Domain join create failed",
        )


@qf_domains_ns.route("/<int:domain_id>/joins/<string:join_id>")
class DomainJoin(ForgeResource):
    @token_required
    def patch(self, domain_id: int, join_id: str):
        def handler() -> Tuple[Any, int]:
            payload = _json_body_dict()
            from_id = payload.get("fromWorkspaceTableId")
            to_id = payload.get("toWorkspaceTableId")
            if from_id is None or to_id is None:
                raise ForgeError("fromWorkspaceTableId and toWorkspaceTableId are required", status_code=400)

            result = DomainJoinService().update_join(
                workspace_id=_workspace_id(),
                domain_id=domain_id,
                join_id=join_id,
                from_workspace_table_id=int(from_id),
                to_workspace_table_id=int(to_id),
                join_type=str(payload.get("joinType") or "LEFT").upper(),
                join_spec=payload.get("joinSpec") or {},
                sort_order=int(payload.get("sortOrder") or 0),
            )
            return result, 200

        return _run(
            handler,
            log_message=f"Domain join update failed domain_id={domain_id} join_id={join_id}",
            client_error="Domain join update failed",
        )

    @token_required
    def delete(self, domain_id: int, join_id: str):
        def handler() -> Tuple[Any, int]:
            result = DomainJoinService().delete_join(
                workspace_id=_workspace_id(),
                domain_id=domain_id,
                join_id=join_id,
            )
            return result, 200

        return _run(
            handler,
            log_message=f"Domain join delete failed domain_id={domain_id} join_id={join_id}",
            client_error="Domain join delete failed",
        )


@qf_domains_ns.route("/<int:domain_id>/users")
class DomainUsers(ForgeResource):
    @token_required
    def get(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            rows = UserDomainReadService().list_domain_users(
                workspace_id=_workspace_id(),
                domain_id=domain_id,
            )
            return {"rows": rows}, 200

        return _run(
            handler,
            log_message=f"Domain users fetch failed domain_id={domain_id}",
            client_error="Domain users fetch failed",
        )

    @token_required
    def post(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            body = _json_body_dict()
            workspace_id = _workspace_id()
            editor_user_id = require_user_id()
            service = DomainUserWriteService()

            if "add" in body or "remove" in body:
                result = service.apply_changes(
                    workspace_id=workspace_id,
                    editor_user_id=editor_user_id,
                    domain_id=domain_id,
                    add=body.get("add") or [],
                    remove=body.get("remove") or [],
                )
                return result, 200

            tarrequire_user_id = (body.get("user_id") or "").strip()
            if not tarrequire_user_id:
                raise ForgeError("user_id is required", status_code=400)

            result = service.upsert_user(
                workspace_id=workspace_id,
                editor_user_id=editor_user_id,
                domain_id=domain_id,
                tarrequire_user_id=tarrequire_user_id,
                can_read=body.get("can_read", True),
                can_edit=body.get("can_edit", False),
            )
            return result, 201

        return _run(
            handler,
            log_message=f"Domain user upsert/apply failed domain_id={domain_id}",
            client_error="Domain user upsert/apply failed",
        )


@qf_domains_ns.route("/<int:domain_id>/users/<string:tarrequire_user_id>")
class DomainUserById(ForgeResource):
    @token_required
    def delete(self, domain_id: int, tarrequire_user_id: str):
        def handler() -> Tuple[Any, int]:
            result = DomainUserWriteService().remove_user(
                workspace_id=_workspace_id(),
                editor_user_id=require_user_id(),
                domain_id=domain_id,
                tarrequire_user_id=tarrequire_user_id,
            )
            return result, 200

        return _run(
            handler,
            log_message=f"Domain user delete failed domain_id={domain_id} tarrequire_user_id={tarrequire_user_id}",
            client_error="Domain user delete failed",
        )


@qf_domains_ns.route("/summary")
class DomainSummary(ForgeResource):
    @token_required
    def get(self):
        def handler() -> Tuple[Any, int]:
            sample_size_raw = request.args.get("sample_size") or "2"
            try:
                sample_size = int(sample_size_raw)
            except ValueError:
                raise ForgeError("sample_size must be an integer", status_code=400)

            rows = DomainSummaryReadService().list_domain_summaries(
                workspace_id=_workspace_id(),
                sample_size=sample_size,
            )
            return {"rows": rows}, 200

        return _run(handler, log_message="Domain summary fetch failed", client_error="Domain summary fetch failed")


@qf_domains_ns.route("/<int:domain_id>/capabilities")
class DomainCapabilities(ForgeResource):
    @token_required
    def get(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            vertical_norm = (request.args.get("vertical_norm") or "generic").strip().lower() or "generic"
            payload = DomainCapabilitiesService().get_domain_capabilities(
                workspace_id=_workspace_id(),
                user_id=require_user_id(),
                domain_id=domain_id,
                vertical_norm=vertical_norm,
            )
            return payload, 200

        return _run(
            handler,
            log_message=f"Domain capabilities fetch failed domain_id={domain_id}",
            client_error="Domain capabilities fetch failed",
        )


@qf_domains_ns.route("/<int:domain_id>/overlay-metrics")
class DomainOverlayMetrics(ForgeResource):
    @token_required
    def get(self, domain_id: int):
        def handler() -> Tuple[Any, int]:
            vertical_norm = (request.args.get("vertical_norm") or "generic").strip().lower() or "generic"
            metrics = DomainCapabilitiesService().get_overlay_metrics(
                workspace_id=_workspace_id(),
                user_id=require_user_id(),
                domain_id=domain_id,
                vertical_norm=vertical_norm,
            )
            return {"domain_id": int(domain_id), "overlay_metrics": metrics}, 200

        return _run(
            handler,
            log_message=f"Domain overlay metrics fetch failed domain_id={domain_id}",
            client_error="Domain overlay metrics fetch failed",
        )


@qf_domains_ns.route("/tables")
class BuilderTables(ForgeResource):
    @token_required
    def get(self):
        def handler() -> Tuple[Any, int]:
            domain_id_raw = request.args.get("domain_id")
            domain_id = int(domain_id_raw) if (domain_id_raw or "").strip() else None
            payload = BuilderColumnFeedService().list_domain_tables(
                workspace_id=_workspace_id(),
                user_id=require_user_id(),
                domain_id=domain_id,
            )
            return payload, 200

        return _run(handler, log_message="Builder tables fetch failed", client_error="Builder tables fetch failed")


@qf_domains_ns.route("/columns")
class BuilderColumns(ForgeResource):
    @token_required
    def get(self):
        def handler() -> Tuple[Any, int]:
            domain_id_raw = request.args.get("domain_id")
            domain_id = int(domain_id_raw) if (domain_id_raw or "").strip() else None

            payload = BuilderColumnFeedService().list_available_columns(
                BuilderFeedQuery(
                    workspace_id=_workspace_id(),
                    user_id=require_user_id(),
                    domain_id=domain_id,
                    table_q=(request.args.get("table_q") or "").strip() or None,
                    column_q=(request.args.get("column_q") or "").strip() or None,
                    variant_code=(request.args.get("variant_code") or "").strip() or None,
                    only_qe=_bool_arg("only_qe", default=None),
                    limit=_int_arg("limit", default=2000),
                    offset=_int_arg("offset", default=0),
                )
            )
            return payload, 200

        return _run(handler, log_message="Builder columns fetch failed", client_error="Builder columns fetch failed")
