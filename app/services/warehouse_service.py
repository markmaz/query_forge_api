from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests

from app.config import DATABRICKS_WAREHOUSE_URL
from app.decorators.validate import validate_params
from app.exceptions.forge_error import ForgeError
from app.models.warehouse import Warehouse
from app.models.workspace import Workspace
from app.services.base_service import build_url, process_response
from app.services.base_token_manager import QF_DATABRICKS_TOKEN, forge_auth_headers
from app.services.workspace_service import WorkspaceService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _WarehouseEndpoint:
    workspace_id: str
    server_name: str


@validate_params("workspace_id")
def get_workspace(workspace_id: str) -> Workspace:
    workspace_data = WorkspaceService().get_workspace(workspace_id=workspace_id)
    if not workspace_data:
        logger.error("Workspace with ID: %s not found", workspace_id)
        raise ForgeError(f"Workspace with ID: {workspace_id} not found", 404)
    return Workspace(**workspace_data)


@validate_params("workspace_id")
def get_server_name(workspace_id: str) -> str:
    workspace = get_workspace(workspace_id)
    if not workspace or not workspace.server:
        logger.error("No server for workspace %s", workspace_id)
        raise ForgeError(f"Workspace {workspace_id} has no associated server.", 404)
    return workspace.server


def parse_warehouse_list(data: Dict[str, List[Dict]]) -> List[Dict]:
    warehouses = data.get("warehouses") or []
    return [Warehouse.from_dict(item).to_dict() for item in warehouses]


class WarehouseService:
    def __init__(self, token_manager: Optional[object] = None) -> None:
        self._token_manager = token_manager

    def _headers(self) -> Dict[str, str]:
        if self._token_manager:
            return self._token_manager.forge_auth_headers()
        return forge_auth_headers(QF_DATABRICKS_TOKEN)

    def _endpoint(self, workspace_id: str) -> _WarehouseEndpoint:
        return _WarehouseEndpoint(
            workspace_id=workspace_id,
            server_name=get_server_name(workspace_id),
        )

    def _list_url(self, workspace_id: str) -> str:
        endpoint = self._endpoint(workspace_id)
        return build_url(endpoint.server_name, DATABRICKS_WAREHOUSE_URL)

    def _detail_url(self, workspace_id: str, warehouse_id: str) -> str:
        endpoint = self._endpoint(workspace_id)
        return build_url(endpoint.server_name, DATABRICKS_WAREHOUSE_URL, warehouse_id)

    @validate_params("workspace_id", "warehouse_name")
    def get_warehouse_by_name(self, workspace_id: str, warehouse_name: str) -> Warehouse:
        warehouses = self.get_all_warehouses(workspace_id)
        expected = warehouse_name.strip().lower()

        for warehouse in warehouses:
            name = getattr(warehouse, "name", None) or warehouse.get("name")
            if name and str(name).strip().lower() == expected:
                return warehouse

        raise ForgeError(f"Warehouse '{warehouse_name}' not found", status_code=404)

    @validate_params("workspace_id")
    def get_all_warehouses(self, workspace_id: str) -> List[Dict]:
        logger.debug("Fetching warehouse list for workspace_id=%s", workspace_id)
        response = requests.get(
            self._list_url(workspace_id),
            headers=self._headers(),
        )
        data = process_response(response)
        return parse_warehouse_list(data)

    @validate_params("workspace_id", "warehouse_id")
    def get_warehouses_for_workspace(self, workspace_id: str, warehouse_id: str) -> Dict:
        response = requests.get(
            self._detail_url(workspace_id, warehouse_id),
            headers=self._headers(),
        )
        return Warehouse.from_dict(process_response(response)).to_dict()

    @validate_params("workspace_id", "warehouse")
    def create_warehouse(self, workspace_id: str, warehouse: Warehouse) -> Dict:
        response = requests.post(
            self._list_url(workspace_id),
            json=warehouse.to_create(),
            headers=self._headers(),
        )
        return process_response(response)

    @validate_params("workspace_id", "warehouse_id")
    def delete_warehouse(self, workspace_id: str, warehouse_id: str) -> Dict:
        response = requests.delete(
            self._detail_url(workspace_id, warehouse_id),
            headers=self._headers(),
        )
        return process_response(response)
