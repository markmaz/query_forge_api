from __future__ import annotations

from dataclasses import dataclass

from flask import g, has_request_context

from app.adapters.databricke_workspace_token_manager import DatabricksWorkspaceForgeTokenPort
from app.adapters.databricks_sql_executor import DatabricksForgeQueryPort
from app.config import DEFAULT_SQL_WAREHOUSE
from app.exceptions.forge_error import ForgeError
from app.services.shared.request_context import resolve_request_username
from app.services.workspace_access_service import WorkspaceAccessService
from app.services.warehouse_service import WarehouseService
from app.services.workspace_service import WorkspaceService


@dataclass(frozen=True)
class CatalogContext:
    workspace_id: str
    workspace_url: str
    warehouse_id: str
    user_name: str
    sql_exec: DatabricksForgeQueryPort


class WorkspaceContextBuilder:
    """
    Mirrors your ValueOverride pattern, but for catalog admin.
    """

    def build(self, workspace_id: str) -> CatalogContext:
        workspace_id = str(workspace_id or "").strip()
        if not workspace_id:
            raise ForgeError("workspace_id is required", status_code=400)

        self._assert_request_workspace_access(workspace_id)

        workspace_url = self._resolve_workspace_url(workspace_id)
        warehouse_id = self._resolve_default_warehouse_id(workspace_id)
        user_name = resolve_request_username()

        token_manager = DatabricksWorkspaceForgeTokenPort(
            workspace_host=workspace_url,
            workspace_id=workspace_id,
        )
        sql_exec = DatabricksForgeQueryPort(
            base_url=workspace_url,
            token_provider=token_manager,
            default_warehouse_id=warehouse_id,
        )

        return CatalogContext(
            workspace_id=workspace_id,
            workspace_url=workspace_url,
            warehouse_id=warehouse_id,
            user_name=user_name,
            sql_exec=sql_exec,
        )

    def _assert_request_workspace_access(self, workspace_id: str) -> None:
        if not has_request_context():
            return

        user_id = str(getattr(g, "user_id", "") or "").strip()
        if not user_id:
            return

        WorkspaceAccessService().assert_workspace_access(user_id=user_id, workspace_id=workspace_id)

    def _resolve_workspace_url(self, workspace_id: str) -> str:
        ws = WorkspaceService().get_workspace(workspace_id=workspace_id)

        if isinstance(ws, dict):
            url = ws.get("server") or ws.get("host_url") or ws.get("workspace_url")
        else:
            url = (
                getattr(ws, "server", None)
                or getattr(ws, "host_url", None)
                or getattr(ws, "workspace_url", None)
            )

        if not url:
            raise ForgeError(
                f"Workspace '{workspace_id}' did not resolve to a server URL",
                status_code=400,
            )

        return str(url).rstrip("/")

    def _resolve_default_warehouse_id(self, workspace_id: str) -> str:
        workspace_url = self._resolve_workspace_url(workspace_id)
        token_manager = DatabricksWorkspaceForgeTokenPort(
            workspace_host=workspace_url,
            workspace_id=workspace_id,
        )
        wh = WarehouseService(token_manager=token_manager).get_warehouse_by_name(
            workspace_id=workspace_id,
            warehouse_name=DEFAULT_SQL_WAREHOUSE,
        )

        warehouse_id = wh.get("warehouse_id") if isinstance(wh, dict) else getattr(wh, "warehouse_id", None)

        if not warehouse_id:
            raise ForgeError(
                f"Default warehouse '{DEFAULT_SQL_WAREHOUSE}' not found for workspace '{workspace_id}'",
                status_code=400,
            )

        return str(warehouse_id)
