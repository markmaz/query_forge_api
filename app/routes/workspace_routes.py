import logging
import re
from typing import Dict, List, Tuple, Union

from flask import request
from flask_restx import Namespace, Resource, fields
from sqlalchemy import text

from app.adapters.databricke_workspace_token_manager import DatabricksWorkspaceTokenManager
from app.adapters.mysql_sql_executor import engine
from app.config import DEFAULT_SQL_WAREHOUSE
from app.decorators.security import token_required
from app.exceptions.service_error import ServiceError
from app.models.warehouse import Warehouse
from app.routes.user_routes import user_model
from app.services.warehouse_service import WarehouseService
from app.services.workspace_inventory.workspace_context import WorkspaceContextBuilder
from app.services.workspace_service import WorkspaceService
from app.services.workspace_user_read_service import WorkspaceUserReadService

logger = logging.getLogger(__name__)

workspace_ns = Namespace("workspaces", description="Workspace related operations")
workspace_model = workspace_ns.model(
    "Workspace",
    {
        "workspace_id": fields.String(required=True, description="Unique identifier for the workspace"),
        "name": fields.String(required=True, description="Name of the workspace"),
        "server": fields.String(required=True, description="The URL of the customer instance")
    },
)

workspace_ns.add_model("User", user_model)
workspace_ns.add_model("Warehouse", Warehouse.warehouse_model)
workspace_ns.add_model("ODBCParams", Warehouse.odbc_params_model)

def json_to_warehouse(json_dict):
    return Warehouse(**json_dict)

def _get_workspace_id_from_header() -> str:
    workspace_id = (request.headers.get("X-Workspace-Id") or "").strip()
    if not workspace_id:
        raise ServiceError("Missing X-Workspace-Id header", status_code=400)
    return workspace_id

def _int_arg(name: str, default: int) -> int:
    v = (request.args.get(name) or "").strip()
    if not v:
        return default
    try:
        return int(v)
    except ValueError:
        raise ServiceError(f"Invalid integer for '{name}'", status_code=400)

def _build_workspace_token_manager(workspace_id: str) -> DatabricksWorkspaceTokenManager:
    ws = WorkspaceService().get_workspace(workspace_id)
    if isinstance(ws, dict):
        server = ws.get("server") or ws.get("host_url") or ws.get("workspace_url")
    else:
        server = getattr(ws, "server", None) or getattr(ws, "host_url", None) or getattr(ws, "workspace_url", None)

    if not server:
        raise ServiceError(f"Workspace {workspace_id} has no associated server.", 404)

    return DatabricksWorkspaceTokenManager(
        workspace_host=str(server).rstrip("/"),
        workspace_id=str(workspace_id),
    )


@workspace_ns.route("/", methods=["GET"])
class Workspaces(Resource):

    @workspace_ns.marshal_list_with(workspace_model)
    @token_required
    def get(self) -> List[Dict]:
        """
        Fetch all available workspaces.

        Returns:
            List[Dict]: A list of workspace objects.
        """
        logger.info("Get all workspaces")
        databricks = WorkspaceService()
        value = databricks.get_all_workspaces()
        logger.info(value)
        return value

@workspace_ns.route("/<string:workspace_id>/")
class WorkSpaceDetails(Resource):

    @workspace_ns.marshal_list_with(workspace_model)
    @workspace_ns.doc(params={"workspace_id": "The ID of the workspace to fetch"})
    @token_required
    def get(self, workspace_id: int) -> Dict:
        """
        Fetch details for a specific workspace.

        :param workspace_id: The ID of the workspace.
        :type workspace_id: int

        Returns:
            Dict: A workspace object.
        """
        databricks = WorkspaceService()
        return databricks.get_workspace(workspace_id)

@workspace_ns.route("/<string:workspace_id>/users")
class WorkspaceUsers(Resource):

    @workspace_ns.marshal_list_with(user_model)
    @workspace_ns.doc(params={"workspace_id": "The ID of the workspace"})
    @token_required
    def get(self, workspace_id: int) -> List[Dict]:
        """
        Fetch all users associated with a workspace.

        :param workspace_id: The ID of the workspace.
        :type workspace_id: int

        Returns:
            List[Dict]: A list of user objects.
        """
        return  WorkspaceService().get_workspace_users_from_dbx(workspace_id)

@workspace_ns.route("/<string:workspace_id>/warehouses")
class WorkspaceAndWarehouseList(Resource):

    @workspace_ns.marshal_list_with(Warehouse.warehouse_model)
    @workspace_ns.doc(params={"workspace_id": "The ID of the workspace"})
    @token_required
    def get(self, workspace_id: int) -> List[Dict]:
        """
        Fetch all warehouses in a specific workspace.

        :param workspace_id: The ID of the workspace.
        :type workspace_id: int

        Returns:
            List[Dict]: A list of warehouse objects.
        """
        token_manager = _build_workspace_token_manager(workspace_id)
        databricks = WarehouseService(token_manager=token_manager)
        return databricks.get_all_warehouses(workspace_id)

    @workspace_ns.expect(Warehouse.warehouse_model)
    @workspace_ns.response(201, "Warehouse created")
    @workspace_ns.doc(security='BearerAuth')
    def post(self, workspace_id: int) -> Union[Tuple[Dict, int], int]:
        """
        Create a new warehouse in a workspace.

        :param workspace_id: The ID of the workspace.
        :type workspace_id: int

        Returns:
            Tuple[Dict, int]: The created warehouse and a status code.
            int: 500 if warehouse creation fails.
        """
        warehouse = Warehouse(**request.json)
        if warehouse:
            token_manager = _build_workspace_token_manager(workspace_id)
            databricks = WarehouseService(token_manager=token_manager)
            value = databricks.create_warehouse(workspace_id=workspace_id, warehouse=warehouse)
            return value, 200
        else:
            return 500

@workspace_ns.route("/<string:workspace_id>/warehouses/default")
class GetDefaultWorkspace(Resource):
    @token_required
    def get(self, workspace_id: str):
        token_manager = _build_workspace_token_manager(workspace_id)
        wh = WarehouseService(token_manager=token_manager).get_warehouse_by_name(
            workspace_id=workspace_id,
            warehouse_name=DEFAULT_SQL_WAREHOUSE,
        )
    
        if hasattr(wh, "to_dict"):
            return wh.to_dict(), 200
        return wh, 200
    
@workspace_ns.route("/<string:workspace_id>/warehouses/<string:warehouse_id>")
class WorkspaceAndWarehouseDetail(Resource):

    @workspace_ns.marshal_list_with(Warehouse.warehouse_model)
    @workspace_ns.doc(params={"workspace_id": "The ID of the workspace", "warehouse_id": "The ID of the warehouse"})
    @token_required
    def get(self, workspace_id: int, warehouse_id: str) -> Dict:
        """
        Fetch details of a specific warehouse within a workspace.

        :param workspace_id: The ID of the workspace.
        :type workspace_id: int
        :param warehouse_id: The ID of the warehouse.
        :type warehouse_id: str

        Returns:
            Dict: A warehouse object.
        """
        token_manager = _build_workspace_token_manager(workspace_id)
        databricks = WarehouseService(token_manager=token_manager)
        return databricks.get_warehouses_for_workspace(workspace_id=workspace_id, warehouse_id=warehouse_id)

    @workspace_ns.response(200, "Warehouse deleted")
    @workspace_ns.doc(security='BearerAuth')
    @token_required

    def delete(self, workspace_id: int, warehouse_id: str) -> Dict:
        """
        Deletes a given SQL warehouse within a workspace.

        :param workspace_id: The ID of the workspace.
        :type workspace_id: int
        :param warehouse_id: The ID of the warehouse.
        :type warehouse_id: str

        Returns:
            Dict: A success message
        """
        token_manager = _build_workspace_token_manager(workspace_id)
        warehouse_service = WarehouseService(token_manager=token_manager)
        return warehouse_service.delete_warehouse(workspace_id, warehouse_id)


@workspace_ns.route("/<string:workspace_id>/namespaces")
class WorkspaceNamespaces(Resource):
    @token_required
    def get(self, workspace_id: str):
        """
        GET /workspaces/<workspace_id>/namespaces
        Returns schemas and catalogs from Databricks (SHOW SCHEMAS / SHOW CATALOGS).
        Optional: ?catalog_name=...
        """
        try:
            catalog_name = (request.args.get("catalog_name") or "").strip() or None
            if catalog_name and not re.match(r"^[A-Za-z0-9_]+$", catalog_name):
                raise ServiceError("Invalid catalog_name", status_code=400)

            ctx = WorkspaceContextBuilder().build(workspace_id)
            sql_exec = ctx.sql_exec

            catalogs: List[str] = []
            try:
                cat_rows = (
                    (sql_exec.submit_statement("SHOW CATALOGS", result_format="ARROW_STREAM") or {}).get("rows")
                    or []
                )
                for row in cat_rows:
                    if not isinstance(row, dict):
                        continue
                    value = row.get("catalog") or row.get("catalog_name") or row.get("name")
                    if value:
                        catalogs.append(str(value))
            except Exception:
                logger.exception("Failed to fetch catalogs from Databricks")

            schema_sql = f"SHOW SCHEMAS IN `{catalog_name}`" if catalog_name else "SHOW SCHEMAS"
            schema_rows = (
                (sql_exec.submit_statement(schema_sql, result_format="ARROW_STREAM") or {}).get("rows") or []
            )
            schemas: List[str] = []
            for row in schema_rows:
                if not isinstance(row, dict):
                    continue
                value = row.get("databaseName") or row.get("schema_name") or row.get("schema") or row.get("name")
                if value:
                    schemas.append(str(value))

            schemas = sorted({s for s in schemas if s})
            catalogs = sorted({c for c in catalogs if c})

            if not schemas:
                sql = """
                    SELECT DISTINCT wt.schema_name, wt.catalog_name
                    FROM workspace_table wt
                    WHERE wt.workspace_id = :ws
                      AND wt.exists_in_dbx = 1
                """
                with engine.connect() as conn:
                    rows = conn.execute(text(sql), {"ws": workspace_id}).mappings().all()

                schemas = sorted({r["schema_name"] for r in rows if r.get("schema_name")})
                if not catalogs:
                    catalogs = sorted({r["catalog_name"] for r in rows if r.get("catalog_name")})

            return {"schemas": schemas, "catalogs": catalogs}, 200

        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Workspace namespaces fetch failed")
            return {"error": "Workspace namespaces fetch failed"}, 500

@workspace_ns.route("/users")
class GetWorkspaceUsersFromSystem(Resource):
    @token_required
    def get(self):
        """
        GET /domains/workspace-users?q=&limit=&offset=
        Returns: { rows: [{ user_id, username, email, first_name, last_name, display_name, status, is_default }] }
        """
        try:
            workspace_id = _get_workspace_id_from_header()
            q = (request.args.get("q") or "").strip() or None
            limit = _int_arg("limit", default=5000)
            offset = _int_arg("offset", default=0)

            rows = WorkspaceUserReadService().list_workspace_users(
                workspace_id=workspace_id,
                q=q,
                limit=limit,
                offset=offset,
                include_inactive=False,
            )
            return {"rows": rows}, 200

        except ServiceError as e:
            return {"error": str(e)}, getattr(e, "status_code", 400) or 400
        except Exception:
            logger.exception("Workspace users fetch failed")
            return {"error": "Workspace users fetch failed"}, 500
