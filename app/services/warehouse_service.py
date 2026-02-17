import logging
from typing import Dict, List, Optional

import requests

from app.config import DATABRICKS_WAREHOUSE_URL
from app.decorators.validate import validate_params
from app.exceptions.service_error import ServiceError
from app.models.warehouse import Warehouse
from app.models.workspace import Workspace
from app.services.base_service import build_url, process_response
from app.services.base_token_manager import DATABRICKS_TOKEN, get_headers
from app.services.workspace_service import WorkspaceService

logger = logging.getLogger(__name__)

def get_server_name(workspace_id: str) -> str:
    """
    Gets the server name of a given workspace.

    :param workspace_id: The ID of the workspace
    :type workspace_id: str

    Returns:
        str: The name of the server
    Raises:
        ServiceError: If the server name is null
    """
    workspace = get_workspace(workspace_id)
    
    if not workspace or not workspace.server:
        logger.error(f"No server for workspace {workspace_id}")
        raise ServiceError(f"Workspace {workspace_id} has no associated server.", 404)
    
    return workspace.server

def get_workspace(workspace_id: str) -> Workspace:
    """
    Fetches workspace data and returns a Workspace instance.
    
    :param workspace_id: The ID of a Databricks workspace
    :type workspace_id: str

    Returns:
        Workspace: A Workspace object
    Raises:
        ServiceError: When the ID is not found or if the request fails.
    """
    workspace_data = WorkspaceService().get_workspace(workspace_id=workspace_id)
    if not workspace_data:
        logger.error(f"Workspace with ID: {workspace_id} not found")
        raise ServiceError(f"Workspace with ID: {workspace_id} not found", 404)
    return Workspace(**workspace_data)

def parse_warehouse_list(data: Dict[str, List[Dict]]) -> List[Dict]:
    """
    Converts a dictionary item into a Warehouse object and into a list of Warehouse dictionary items.

    :param data: A dictionary containing a list of warehouses
    :type data: Dict[str, List[Dict]]

    Returns:
        List[Dict]: A list of Warehouse dictionaries
    """
    return [Warehouse.from_dict(item).to_dict() for item in data["warehouses"]]


class WarehouseService:
    def __init__(self, token_manager: Optional[object] = None) -> None:
        self._token_manager = token_manager

    def _headers(self) -> Dict[str, str]:
        if self._token_manager:
            return self._token_manager.get_headers()
        return get_headers(DATABRICKS_TOKEN)

    @validate_params("workspace_id", "warehouse_name")
    def get_warehouse_by_name(
        self,
        workspace_id: str,
        warehouse_name: str
    ) -> Warehouse:
        warehouses = self.get_all_warehouses(workspace_id)

        for w in warehouses:
            name = getattr(w, "name", None) or w.get("name")
            if name and name.strip().lower() == warehouse_name.strip().lower():
                return w

        raise ServiceError(
            f"Warehouse '{warehouse_name}' not found",
            status_code=404
    )

    @validate_params("workspace_id")
    def get_all_warehouses(self, workspace_id: str) -> List[Dict]:
        """
        Get all SQL warehouses for a given workspace.
        
        :param workspace_id: The ID of a Databricks workspace
        :type workspace_id: str

        Returns:
            List[Dict]: A list of Warehouse dictionaries
        Raises:
            ServiceError: When the request fails
        """
        logger.debug("Fetching warehouse list for workspace_id=%s", workspace_id)
        response = requests.get(
            build_url(get_server_name(workspace_id), DATABRICKS_WAREHOUSE_URL),
            headers=self._headers(),
        )
        data = process_response(response)
        return parse_warehouse_list(data)

    @validate_params("workspace_id", "warehouse_id")
    def get_warehouses_for_workspace(self, workspace_id: str, warehouse_id: str) -> Dict:
        """
        Get a specific SQL warehouse for a given workspace.
        
        :param workspace_id: The ID of a Databricks workspace
        :type workspace_id: str
        :param warehouse_id: The ID of a Databricks SQL warehouse
        :type warehouse_id: str

        Returns:
            Dict: A dictionary representing a Warehouse object
        Raises:
            ServiceError: If the request fails
        """
        response = requests.get(
            build_url(get_server_name(workspace_id), DATABRICKS_WAREHOUSE_URL, warehouse_id),
            headers=self._headers(),
        )
        return Warehouse.from_dict(process_response(response)).to_dict()
    
    @validate_params("workspace_id", "warehouse")
    def create_warehouse(self, workspace_id: str, warehouse: Warehouse) -> Dict:
        """
        Creates an SQL warehouse in a given workspace.
        
        :param workspace_id: The ID of a Databricks workspace
        :type workspace_id: str
        :param warehouse: The SQL Warehouse model object
        :type warehouse: Warehouse

        Returns:
            Dict: The response dictionary from the API
        Raises:
            ServiceError: If the request fails
        """
        response = requests.post(
            build_url(get_server_name(workspace_id), DATABRICKS_WAREHOUSE_URL),
            json=warehouse.to_create(),
            headers=self._headers(),
        )
        return process_response(response)
        
    @validate_params("workspace_id", "warehouse_id")
    def delete_warehouse(self, workspace_id: str, warehouse_id: str) -> Dict:
        """
        Deletes a given SQL warehouse from a given workspace.
        
        :param workspace_id: The ID of a Databricks workspace
        :type workspace_id: str
        :param warehouse_id: The ID of a Databricks SQL warehouse
        :type warehouse_id: str

        Returns:
            Dict: The response dictionary from the API
        Raises:
            ServiceError: When the request fails
        """
        response = requests.delete(
            build_url(get_server_name(workspace_id), DATABRICKS_WAREHOUSE_URL, warehouse_id),
            headers=self._headers(),
        )
        return process_response(response)
