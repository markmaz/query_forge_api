import logging
from typing import Dict, List

import requests

from app.config import DATABRICKS_BASE_ACCOUNT_URL, DATABRICKS_WORKSPACE_USERS_URL, DATABRICKS_WORKSPACES
from app.decorators.validate import validate_params
from app.exceptions.service_error import ServiceError
from app.models.user import User
from app.models.workspace import Workspace
from app.services.base_service import build_url, process_response
from app.services.base_token_manager import DATABRICKS_TOKEN, get_headers

logger = logging.getLogger(__name__)

class WorkspaceService:
    def get_all_workspaces(self) -> List[Dict[str, str]]:
        """
        Get all workspaces associated with our account.
        
        Returns: 
            List of workspace dictionaries
        Raises:
            ServiceError: If the API request fails
        """
        response = requests.get(build_url(DATABRICKS_BASE_ACCOUNT_URL, DATABRICKS_WORKSPACES), headers=get_headers(DATABRICKS_TOKEN))
        data = process_response(response)

        workspaces = [
            Workspace(
                workspace_id=item["workspace_id"],
                name=item["workspace_name"],
                server=item["deployment_name"]
            )
            for item in data
        ]
        return [ws.model_dump() for ws in workspaces]

    @validate_params("workspace_id")
    def get_workspace_users_from_dbx(self, workspace_id: str) -> List[Dict[str, str]]:
        """
        Retrieve all the users for a given workspace.
        
        :param workspace_id: The ID of a Databricks workspace
        :type workspace_id: str

        Returns:
            List of user dictionaries
        Raises:
            ServiceError: If the API request fails
        """
        try:
            ws = self.get_workspace(workspace_id)
        except ServiceError:
            logger.error(f"Workspace not found. Workspace ID: {workspace_id}")
            raise ServiceError(f"Workspace {workspace_id} not found", 404)
        
        response = requests.get(build_url(ws['server'], DATABRICKS_WORKSPACE_USERS_URL), headers=get_headers(DATABRICKS_TOKEN))
        data = process_response(response)

        users = data.get("Resources", [])
        organization = ws.get('name', '')

        user_details = [
            User(
                first_name=item.get("name", {}).get("givenName", ""),
                last_name=item.get("name", {}).get("familyName", ""),
                organization=organization,
                display_name=item.get("displayName", ""),
                user_name=item.get("userName", "")
            )
            for item in users
        ]
        return [ud.model_dump(mode="json") for ud in user_details]

    @validate_params("workspace_id")
    def get_workspace(self, workspace_id: str) -> Dict[str, str]:
        """
        Get a specific workspace.
        
        :param workspace_id: The ID of a Databricks workspace
        :type workspace_id: str

        Returns:
            A dictionary representing the Workspace object
        Raises:
            ServiceError: If the request fails
        """
        logger.debug("Fetching workspace metadata for workspace_id=%s", workspace_id)
        response = requests.get(build_url(DATABRICKS_BASE_ACCOUNT_URL, DATABRICKS_WORKSPACES, workspace_id), headers=get_headers(DATABRICKS_TOKEN))
        data = process_response(response)

        workspace = Workspace(
            workspace_id=data["workspace_id"],
            name=data["workspace_name"],
            server=data["deployment_name"]
        )
        return workspace.model_dump()
