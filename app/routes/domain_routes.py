# app/routes/domain_routes.py
from __future__ import annotations

import logging
from typing import Optional

from flask import request
from flask_restx import Namespace, Resource

from app.decorators.security import token_required
from app.exceptions.service_error import ServiceError
from app.services.domain.builder_column_feed_service import (
    BuilderColumnFeedService,
    BuilderFeedQuery,
)
from app.services.domain.domain_admin_write_service import DomainAdminWriteService
from app.services.domain.domain_column_sample_read_service import DomainColumnSampleReadService
from app.services.domain.domain_join_service import DomainJoinService
from app.services.domain.domain_summary_read_service import DomainSummaryReadService
from app.services.domain.domain_table_read_service import DomainTableReadService
from app.services.domain.domain_table_write_service import DomainTableWriteService
from app.services.domain.domain_user_read_service import UserDomainReadService
from app.services.domain.domain_user_write_service import DomainUserWriteService
from app.services.shared.request_context import get_current_username

logger = logging.getLogger(__name__)
domains_ns = Namespace("domains", description="Domains + Builder feed + permissions")


# ----------------------------
# Helpers
# ----------------------------


def _get_workspace_id_from_header() -> str:
    workspace_id = (request.headers.get("X-Workspace-Id") or "").strip()
    if not workspace_id:
        raise ServiceError("Missing X-Workspace-Id header", status_code=400)
    return workspace_id

def _handle_service_error(e: ServiceError):
    return {"error": str(e)}, getattr(e, "status_code", 400) or 400

def _get_user_id() -> str:
    user_id = (request.headers.get("X-User-Id") or "").strip()
    if user_id:
        return user_id
    return get_current_username()


def _int_arg(name: str, default: int) -> int:
    v = (request.args.get(name) or "").strip()
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        raise ServiceError(f"Invalid integer for '{name}'", status_code=400)


def _bool_arg(name: str, default: Optional[bool] = None) -> Optional[bool]:
    v = (request.args.get(name) or "").strip().lower()
    if v == "":
        return default
    if v in ("1", "true", "yes", "y", "on"):
        return True
    if v in ("0", "false", "no", "n", "off"):
        return False
    raise ServiceError(f"Invalid boolean for '{name}'", status_code=400)


# ----------------------------
# Domains (CRUD)
# ----------------------------

@domains_ns.route("/")
class DomainsRoot(Resource):
    @token_required
    def get(self):
        """
        GET /domains
        Returns domains the current user can read.
        """
        try:
            workspace_id = _get_workspace_id_from_header()
            user_id = _get_user_id()

            rows = UserDomainReadService().list_user_domains(
                workspace_id=workspace_id,
                user_id=user_id,
            )
            return {"rows": rows}, 200

        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Domains fetch failed")
            return {"error": "Domains fetch failed"}, 500

    @token_required
    def post(self):
        """
        POST /domains
        Body: {name, kind?, description?}
        """
        try:
            workspace_id = _get_workspace_id_from_header()
            user_id = _get_user_id()

            body = request.get_json(silent=True) or {}
            if not isinstance(body, dict):
                raise ServiceError("Invalid JSON body", status_code=400)

            row = DomainAdminWriteService().create_domain(
                workspace_id=workspace_id,
                user_id=user_id,
                name=(body.get("name") or "").strip(),
                kind=body.get("kind"),
                description=body.get("description"),
                model_table_id=body.get("model_table_id"),
                column_name_policy=body.get("column_name_policy"),
            )
            return {"row": row}, 201

        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Domain create failed")
            return {"error": "Domain create failed"}, 500


@domains_ns.route("/<int:domain_id>")
class DomainById(Resource):
    @token_required
    def patch(self, domain_id: int):
        """
        PATCH /domains/<id>
        Body: {name?, kind?, description?, is_active?}
        """
        try:
            workspace_id = _get_workspace_id_from_header()
            user_id = _get_user_id()

            body = request.get_json(silent=True) or {}
            if not isinstance(body, dict):
                raise ServiceError("Invalid JSON body", status_code=400)

            row = DomainAdminWriteService().patch_domain(
                workspace_id=workspace_id,
                user_id=user_id,
                domain_id=domain_id,
                model_table_id=body.get("model_table_id") if "model_table_id" in body else None,
                name=body.get("name") if "name" in body else None,
                kind=body.get("kind") if "kind" in body else None,
                description=body.get("description") if "description" in body else None,
                is_active=body.get("is_active") if "is_active" in body else None,
                column_name_policy=body.get("column_name_policy") if "column_name_policy" in body else None,
            )
            return {"row": row}, 200

        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Domain patch failed id=%s", domain_id)
            return {"error": "Domain patch failed"}, 500

    @token_required
    def delete(self, domain_id: int):
        """
        DELETE /domains/<id>
        """
        try:
            workspace_id = _get_workspace_id_from_header()
            user_id = _get_user_id()

            res = DomainAdminWriteService().delete_domain(
                workspace_id=workspace_id,
                user_id=user_id,
                domain_id=domain_id,
            )
            return res, 200

        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Domain delete failed id=%s", domain_id)
            return {"error": "Domain delete failed"}, 500

@domains_ns.route("/column-sample")
class ColumnSample(Resource):
    @token_required
    def get(self):
        """
        GET /domains/column-sample?workspace_table_id=&column_name=&limit=10
        headers:
          - X-Workspace-Id
        """
        try:
            workspace_id = _get_workspace_id_from_header()
            user_id = _get_user_id()

            wtid = request.args.get("workspace_table_id")
            if not (wtid or "").strip():
                raise ServiceError("workspace_table_id is required", status_code=400)

            column_name = (request.args.get("column_name") or "").strip()
            if not column_name:
                raise ServiceError("column_name is required", status_code=400)

            limit = _int_arg("limit", default=10)

            svc = DomainColumnSampleReadService()
            payload = svc.sample_column_values(
                workspace_id=workspace_id,
                user_id=user_id,
                workspace_table_id=int(wtid),
                column_name=column_name,
                limit=limit,
            )

            return payload, 200

        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Column sample failed")
            return {"error": "Column sample failed"}, 500

# ----------------------------
# Workspace tables picker (Admin)
# Canonical: /domains/workspace-tables
# ----------------------------

@domains_ns.route("/workspace-tables")
class WorkspaceTables(Resource):
    @token_required
    def get(self):
        """
        GET /domains/workspace-tables?q=&schema_name=&catalog_name=&only_exists_in_dbx=&limit=&offset=
        Used by Domain admin UI to pick tables to map into domains.
        """
        try:
            workspace_id = _get_workspace_id_from_header()

            q = (request.args.get("q") or "").strip() or None
            schema_name = (request.args.get("schema_name") or "").strip() or None
            catalog_name = (request.args.get("catalog_name") or "").strip() or None
            only_exists_in_dbx = _bool_arg("only_exists_in_dbx", default=True)

            limit = _int_arg("limit", default=500)
            offset = _int_arg("offset", default=0)

            mapped = _bool_arg("mapped", default=None)  # Optional[bool]

            rows = DomainTableReadService().list_workspace_tables(
                workspace_id=workspace_id,
                q=q,
                schema_name=schema_name,
                catalog_name=catalog_name,
                only_exists_in_dbx=only_exists_in_dbx,
                limit=limit,
                offset=offset,
                mapped=mapped,
)
            return {"rows": rows}, 200

        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Workspace tables fetch failed")
            return {"error": "Workspace tables fetch failed"}, 500


# ----------------------------
# Domain ⇄ workspace tables mapping (Admin)
# Canonical:
#   GET  /domains/<id>/tables
#   POST /domains/<id>/tables  { add:[], remove:[] }
# ----------------------------

@domains_ns.route("/<int:domain_id>/tables")
class DomainTables(Resource):
    @token_required
    def get(self, domain_id: int):
        """
        GET /domains/<domain_id>/tables
        """
        try:
            workspace_id = _get_workspace_id_from_header()
            rows = DomainTableReadService().list_domain_tables(
                workspace_id=workspace_id,
                domain_id=domain_id,
            )
            return {"rows": rows}, 200

        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Domain tables fetch failed domain_id=%s", domain_id)
            return {"error": "Domain tables fetch failed"}, 500

    @token_required
    def post(self, domain_id: int):
        """
        POST /domains/<domain_id>/tables
        Body: { add: number[], remove: number[] }
        OR
        Body: { workspaceTableId, relationKind?, role?, sortOrder?, tableAlias? }
        """
        try:
            workspace_id = _get_workspace_id_from_header()
            user_id = _get_user_id()

            body = request.get_json(silent=True) or {}
            if not isinstance(body, dict):
                raise ServiceError("Invalid JSON body", status_code=400)

            if "workspaceTableId" in body:
                wtid = body.get("workspaceTableId")
                if wtid is None:
                    raise ServiceError("workspaceTableId is required", status_code=400)

                row = DomainTableWriteService().add_or_update_table(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    domain_id=domain_id,
                    workspace_table_id=int(wtid),
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

            # Let the service normalize/validate; these may be missing or null
            add_ids = body.get("add")
            remove_ids = body.get("remove")

            res = DomainTableWriteService().apply_changes(
                workspace_id=workspace_id,
                user_id=user_id,
                domain_id=domain_id,
                add=add_ids,
                remove=remove_ids,
            )
            return res, 200

        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Domain tables update failed domain_id=%s", domain_id)
            return {"error": "Domain tables update failed"}, 500


@domains_ns.route("/<int:domain_id>/tables/<int:workspace_table_id>/primary")
class DomainPrimaryTable(Resource):
    @token_required
    def patch(self, domain_id: int, workspace_table_id: int):
        """
        PATCH /domains/<domain_id>/tables/<workspace_table_id>/primary
        Body: { "isPrimary": true }
        """
        try:
            workspace_id = _get_workspace_id_from_header()
            payload = request.get_json(silent=True) or {}
            is_primary = payload.get("isPrimary") is True
            if not is_primary:
                raise ServiceError("isPrimary must be true", status_code=400)

            result = DomainJoinService().set_primary_table(
                workspace_id=workspace_id,
                domain_id=domain_id,
                workspace_table_id=workspace_table_id,
            )
            return {"rows": result}, 200
        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Domain primary table update failed domain_id=%s", domain_id)
            return {"error": "Domain primary table update failed"}, 500

# ----------------------------
# Domain table joins
# Canonical:
#   GET    /domains/<id>/joins
#   POST   /domains/<id>/joins
#   PATCH  /domains/<id>/joins/<join_id>
#   DELETE /domains/<id>/joins/<join_id>
# ----------------------------

@domains_ns.route("/<int:domain_id>/joins")
class DomainJoins(Resource):
    @token_required
    def get(self, domain_id: int):
        try:
            workspace_id = _get_workspace_id_from_header()
            rows = DomainJoinService().list_domain_joins(workspace_id=workspace_id, domain_id=domain_id)
            return {"rows": rows}, 200
        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Domain joins fetch failed domain_id=%s", domain_id)
            return {"error": "Domain joins fetch failed"}, 500

    @token_required
    def post(self, domain_id: int):
        try:
            workspace_id = _get_workspace_id_from_header()
            payload = request.get_json(silent=True) or {}

            from_id = payload.get("fromWorkspaceTableId")
            to_id = payload.get("toWorkspaceTableId")
            join_type = payload.get("joinType") or "LEFT"
            join_spec = payload.get("joinSpec") or {}
            sort_order = payload.get("sortOrder") or 0

            if from_id is None or to_id is None:
                raise ServiceError("fromWorkspaceTableId and toWorkspaceTableId are required", status_code=400)

            result = DomainJoinService().create_join(
                workspace_id=workspace_id,
                domain_id=domain_id,
                from_workspace_table_id=int(from_id),
                to_workspace_table_id=int(to_id),
                join_type=str(join_type).upper(),
                join_spec=join_spec,
                sort_order=int(sort_order),
            )
            return result, 200
        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Domain join create failed domain_id=%s", domain_id)
            return {"error": "Domain join create failed"}, 500


@domains_ns.route("/<int:domain_id>/joins/<string:join_id>")
class DomainJoin(Resource):
    @token_required
    def patch(self, domain_id: int, join_id: str):
        try:
            workspace_id = _get_workspace_id_from_header()
            payload = request.get_json(silent=True) or {}

            from_id = payload.get("fromWorkspaceTableId")
            to_id = payload.get("toWorkspaceTableId")
            join_type = payload.get("joinType") or "LEFT"
            join_spec = payload.get("joinSpec") or {}
            sort_order = payload.get("sortOrder") or 0

            if from_id is None or to_id is None:
                raise ServiceError("fromWorkspaceTableId and toWorkspaceTableId are required", status_code=400)

            result = DomainJoinService().update_join(
                workspace_id=workspace_id,
                domain_id=domain_id,
                join_id=join_id,
                from_workspace_table_id=int(from_id),
                to_workspace_table_id=int(to_id),
                join_type=str(join_type).upper(),
                join_spec=join_spec,
                sort_order=int(sort_order),
            )
            return result, 200
        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Domain join update failed domain_id=%s join_id=%s", domain_id, join_id)
            return {"error": "Domain join update failed"}, 500

    @token_required
    def delete(self, domain_id: int, join_id: str):
        try:
            workspace_id = _get_workspace_id_from_header()
            result = DomainJoinService().delete_join(
                workspace_id=workspace_id,
                domain_id=domain_id,
                join_id=join_id,
            )
            return result, 200
        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Domain join delete failed domain_id=%s join_id=%s", domain_id, join_id)
            return {"error": "Domain join delete failed"}, 500

# ----------------------------
# Domain ⇄ users mapping (Admin)
# ----------------------------

@domains_ns.route("/<int:domain_id>/users")
class DomainUsers(Resource):
    @token_required
    def get(self, domain_id: int):
        """
        GET /domains/<id>/users
        Lists users assigned to this domain.
        """
        try:
            workspace_id = _get_workspace_id_from_header()
            rows = UserDomainReadService().list_domain_users(
                workspace_id=workspace_id,
                domain_id=domain_id,
            )
            return {"rows": rows}, 200

        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Domain users fetch failed domain_id=%s", domain_id)
            return {"error": "Domain users fetch failed"}, 500

    @token_required
    def post(self, domain_id: int):
        """
        POST /domains/<id>/users

        Supports BOTH:
        1) Single upsert:
           { user_id: string, can_read?: bool, can_edit?: bool }

        2) Batch apply (matches FE):
           { add: [{user_id: string, can_edit?: bool}], remove: [user_id] }
        """
        try:
            workspace_id = _get_workspace_id_from_header()
            editor_user_id = _get_user_id()

            body = request.get_json(silent=True) or {}
            if not isinstance(body, dict):
                raise ServiceError("Invalid JSON body", status_code=400)

            svc = DomainUserWriteService()

            # ✅ Batch path
            if "add" in body or "remove" in body:
                add = body.get("add") or []
                remove = body.get("remove") or []

                res = svc.apply_changes(
                    workspace_id=workspace_id,
                    editor_user_id=editor_user_id,
                    domain_id=domain_id,
                    add=add,
                    remove=remove,
                )
                return res, 200

            target_user_id = (body.get("user_id") or "").strip()
            if not target_user_id:
                raise ServiceError("user_id is required", status_code=400)

            res = svc.upsert_user(
                workspace_id=workspace_id,
                editor_user_id=editor_user_id,
                domain_id=domain_id,
                target_user_id=target_user_id,
                can_read=body.get("can_read", True),
                can_edit=body.get("can_edit", False),
            )
            return res, 201

        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Domain user upsert/apply failed domain_id=%s", domain_id)
            return {"error": "Domain user upsert/apply failed"}, 500


@domains_ns.route("/<int:domain_id>/users/<string:target_user_id>")
class DomainUserById(Resource):
    @token_required
    def delete(self, domain_id: int, target_user_id: str):
        """
        DELETE /domains/<id>/users/<user_id>
        Requires can_edit on domain.
        """
        try:
            workspace_id = _get_workspace_id_from_header()
            editor_user_id = _get_user_id()

            res = DomainUserWriteService().remove_user(
                workspace_id=workspace_id,
                editor_user_id=editor_user_id,
                domain_id=domain_id,
                target_user_id=target_user_id,
            )
            return res, 200

        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Domain user delete failed domain_id=%s target_user_id=%s", domain_id, target_user_id)
            return {"error": "Domain user delete failed"}, 500


# ----------------------------
# Domain summaries (Admin list chips)
# ----------------------------

@domains_ns.route("/summary")
class DomainSummary(Resource):
    @token_required
    def get(self):
        """
        GET /domains/summary?sample_size=2
        Returns: { rows: [{ id, table_count, table_sample: string[] }] }
        """
        try:
            workspace_id = _get_workspace_id_from_header()

            sample_size = request.args.get("sample_size") or "2"
            try:
                sample_size_i = int(sample_size)
            except ValueError:
                raise ServiceError("sample_size must be an integer", status_code=400)

            rows = DomainSummaryReadService().list_domain_summaries(
                workspace_id=workspace_id,
                sample_size=sample_size_i,
            )
            return {"rows": rows}, 200

        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Domain summary fetch failed")
            return {"error": "Domain summary fetch failed"}, 500


# ----------------------------
# Builder feed (Query Builder runtime)
# KEEP these endpoints as-is (they are not admin CRUD)
# ----------------------------

@domains_ns.route("/tables")
class BuilderTables(Resource):
    @token_required
    def get(self):
        """
        GET /domains/tables?domain_id=
        Returns only tables the user can see through domains.
        (Builder feed endpoint)
        """
        try:
            workspace_id = _get_workspace_id_from_header()
            user_id = _get_user_id()

            domain_id = request.args.get("domain_id")
            domain_id = int(domain_id) if (domain_id or "").strip() else None

            payload = BuilderColumnFeedService().list_domain_tables(
                workspace_id=workspace_id,
                user_id=user_id,
                domain_id=domain_id,
            )
            return payload, 200

        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Builder tables fetch failed")
            return {"error": "Builder tables fetch failed"}, 500


@domains_ns.route("/columns")
class BuilderColumns(Resource):
    @token_required
    def get(self):
        """
        GET /domains/columns?... (builder feed)
        """
        try:
            workspace_id = _get_workspace_id_from_header()
            user_id = _get_user_id()

            domain_id = request.args.get("domain_id")
            domain_id = int(domain_id) if (domain_id or "").strip() else None

            table_q = (request.args.get("table_q") or "").strip() or None
            column_q = (request.args.get("column_q") or "").strip() or None
            variant_code = (request.args.get("variant_code") or "").strip() or None
            only_qe = _bool_arg("only_qe", default=None)

            limit = _int_arg("limit", default=2000)
            offset = _int_arg("offset", default=0)

            payload = BuilderColumnFeedService().list_available_columns(
                BuilderFeedQuery(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    domain_id=domain_id,
                    table_q=table_q,
                    column_q=column_q,
                    variant_code=variant_code,
                    only_qe=only_qe,
                    limit=limit,
                    offset=offset,
                )
            )
            return payload, 200

        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Builder columns fetch failed")
            return {"error": "Builder columns fetch failed"}, 500
