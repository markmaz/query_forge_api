from __future__ import annotations

import logging
import re

from flask import g, request
from flask_restx import Namespace, fields
from app.routes.forge_resource import ForgeResource
from sqlalchemy import text

from app.adapters.mysql_sql_executor import engine
from app.decorators.security import token_required
from app.decorators.rbac import require_access, require_admin
from app.exceptions.forge_error import ForgeError
from app.routes.user_routes import user_model
from app.services.workspace_inventory.workspace_context import WorkspaceSqlContextBuilder
from app.services.workspace_access_service import WorkspaceAccessService
from app.services.workspace_service import WorkspaceService
from app.services.workspace_user_read_service import WorkspaceUserReadService
from app.services.tenancy.workspace_external_link_service import WorkspaceExternalLinkService

logger = logging.getLogger(__name__)

workspace_ns = Namespace("workspaces", description="Workspace related operations")
workspace_model = workspace_ns.model(
    "Workspace",
    {
        "workspace_id": fields.String(required=True, description="Unique identifier for the workspace"),
        "name": fields.String(required=True, description="Name of the workspace"),
        "server": fields.String(required=True, description="The URL of the customer instance"),
    },
)
workspace_ns.add_model("User", user_model)


def _workspace_service() -> WorkspaceService:
    return WorkspaceService()


def _workspace_id_header() -> str:
    workspace_id = (request.headers.get("X-Workspace-Id") or "").strip()
    if not workspace_id:
        raise ForgeError("Missing X-Workspace-Id header", status_code=400)
    return workspace_id


def _int_arg(name: str, default: int) -> int:
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ForgeError(f"Invalid integer for '{name}'", status_code=400) from exc



@workspace_ns.route("/", methods=["GET"])
class Workspaces(ForgeResource):
    @workspace_ns.marshal_list_with(workspace_model)
    @token_required
    @require_access("workspaces")
    def get(self):
        logger.info("Get all workspaces")
        return _workspace_service().get_all_workspaces()


@workspace_ns.route("/<string:workspace_id>/")
class WorkSpaceDetails(ForgeResource):
    @workspace_ns.marshal_list_with(workspace_model)
    @workspace_ns.doc(params={"workspace_id": "The ID of the workspace to fetch"})
    @token_required
    @require_access("workspaces")
    def get(self, workspace_id: str):
        return _workspace_service().get_workspace(workspace_id)


@workspace_ns.route("/<string:workspace_id>/users")
class WorkspaceUsers(ForgeResource):
    @workspace_ns.marshal_list_with(user_model)
    @workspace_ns.doc(params={"workspace_id": "The ID of the workspace"})
    @token_required
    @require_admin()
    def get(self, workspace_id: str):
        return _workspace_service().get_workspace_users_from_dbx(workspace_id)



@workspace_ns.route("/<string:workspace_id>/namespaces")
class WorkspaceNamespaces(ForgeResource):
    @token_required
    @require_access("workspaces")
    def get(self, workspace_id: str):
        try:
            catalog_name = (request.args.get("catalog_name") or "").strip() or None
            if catalog_name and not re.match(r"^[A-Za-z0-9_]+$", catalog_name):
                raise ForgeError("Invalid catalog_name", status_code=400)

            sql_exec = WorkspaceSqlContextBuilder().build(workspace_id).sql_exec

            catalogs: list[str] = []
            try:
                catalog_rows = (sql_exec.submit_statement("SHOW CATALOGS", qf_result_fmt="ARROW_STREAM") or {}).get("rows") or []
                for row in catalog_rows:
                    if not isinstance(row, dict):
                        continue
                    value = row.get("catalog") or row.get("catalog_name") or row.get("name")
                    if value:
                        catalogs.append(str(value))
            except Exception:
                logger.exception("Failed to fetch catalogs from Databricks")

            schema_sql = f"SHOW SCHEMAS IN `{catalog_name}`" if catalog_name else "SHOW SCHEMAS"
            schema_rows = (sql_exec.submit_statement(schema_sql, qf_result_fmt="ARROW_STREAM") or {}).get("rows") or []
            schemas: list[str] = []
            for row in schema_rows:
                if not isinstance(row, dict):
                    continue
                value = row.get("databaseName") or row.get("schema_name") or row.get("schema") or row.get("name")
                if value:
                    schemas.append(str(value))

            schemas = sorted({name for name in schemas if name})
            catalogs = sorted({name for name in catalogs if name})

            if not schemas:
                fallback_sql = """
                    SELECT DISTINCT wt.schema_name, wt.catalog_name
                    FROM workspace_table wt
                    WHERE wt.workspace_id = :ws
                      AND wt.exists_in_dbx = 1
                """
                with engine.connect() as conn:
                    rows = conn.execute(text(fallback_sql), {"ws": workspace_id}).mappings().all()

                schemas = sorted({row["schema_name"] for row in rows if row.get("schema_name")})
                if not catalogs:
                    catalogs = sorted({row["catalog_name"] for row in rows if row.get("catalog_name")})

            return {"schemas": schemas, "catalogs": catalogs}, 200
        except ForgeError as exc:
            return {"error": str(exc)}, getattr(exc, "status_code", 400) or 400
        except Exception:
            logger.exception("Workspace namespaces fetch failed")
            return {"error": "Workspace namespaces fetch failed"}, 500


@workspace_ns.route("/users")
class GetWorkspaceUsersFromSystem(ForgeResource):
    @token_required
    @require_admin()
    def get(self):
        try:
            rows = WorkspaceUserReadService().list_workspace_users(
                workspace_id=_workspace_id_header(),
                q=(request.args.get("q") or "").strip() or None,
                limit=_int_arg("limit", default=5000),
                offset=_int_arg("offset", default=0),
                include_inactive=False,
            )
            return {"rows": rows}, 200
        except ForgeError as exc:
            return {"error": str(exc)}, getattr(exc, "status_code", 400) or 400
        except Exception:
            logger.exception("Workspace users fetch failed")
            return {"error": "Workspace users fetch failed"}, 500


@workspace_ns.route("/<string:workspace_id>/external-links")
class WorkspaceExternalLinks(ForgeResource):
    @token_required
    @require_access("workspaces")
    def get(self, workspace_id: str):
        try:
            user_id = str(getattr(g, "user_id", "") or "").strip()
            if user_id:
                WorkspaceAccessService().assert_workspace_access(user_id=user_id, workspace_id=workspace_id)
            allow_legacy_fallback = str(request.args.get("legacy_fallback") or "").strip().lower() in {
                "",
                "1",
                "true",
                "yes",
                "y",
                "on",
            }
            result = WorkspaceExternalLinkService().list_links(
                workspace_id=workspace_id,
                allow_legacy_fallback=allow_legacy_fallback,
            )
            return result, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("workspace external links fetch failed")
            return {"error": "workspace external links fetch failed"}, 500
