import logging
import time
import uuid
from typing import Dict, List
from urllib.parse import urlparse

import jwt
import requests

from app.config import (
    JWT_ALGORITHM,
    SIGMA_BASE_URL,
    SIGMA_JWT_BASE_URL,
    SIGMA_JWT_CLIENT_ID,
    SIGMA_JWT_CLIENT_SECRET,
    SIGMA_TAG_URL,
)
from app.decorators.validate import validate_params
from app.exceptions.service_error import ServiceError
from app. models.connection import Connection
from app.models.sigma_claim import SigmaClaim
from app.models.workspace import Workspace
from app.services.base_service import build_url, process_response
from app.services.base_token_manager import SIGMA_TOKEN, get_headers
from app.services.connection_service import ConnectionService
from app.services.user_service import UserService
from app.services.workspace_service import WorkspaceService
from app.utils.param_builder import ParamBuilder

logger = logging.getLogger(__name__)
WORKSPACES = "workspaces"
WORKBOOKS = "workbooks"
EMBEDS = "embeds"
UTF8 = "utf-8"
TEAM_ID = "9415c696-28d1-49fc-91ea-f120124b6eb8"
SIGMA_TIMEOUT_SECONDS = 5

class DashboardService:
    def _safe_get(self, url: str, **kwargs):
        try:
            return requests.get(url, timeout=SIGMA_TIMEOUT_SECONDS, **kwargs)
        except requests.RequestException:
            raise ServiceError("Sigma API unavailable", status_code=424)

    def _safe_post(self, url: str, **kwargs):
        try:
            return requests.post(url, timeout=SIGMA_TIMEOUT_SECONDS, **kwargs)
        except requests.RequestException:
            raise ServiceError("Sigma API unavailable", status_code=424)
    
    def get_workspaces(self) -> List[Dict]:
        """
        Get all the available Sigma workspaces.

        Returns:
            List[Dict]: A list of all the workspaces.
        """
        response = self._safe_get(build_url(SIGMA_BASE_URL, WORKSPACES), headers=get_headers(SIGMA_TOKEN))
        return process_response(response)

    def get_workbooks(self) -> List[Dict]:
        """
        Get all the available Sigma workbooks.

        Returns:
            List[Dict]: A list of all the workbooks.
        """
        all_wbs =[]
        params = {}

        while True:
            response = self._safe_get(
                build_url(SIGMA_BASE_URL, WORKBOOKS),
                headers=get_headers(SIGMA_TOKEN),
                params=params,
            )
            response.raise_for_status()

            data = response.json()
    
            all_wbs.extend(data.get("entries"))
            next_page = data.get("nextPage")

            if not next_page:
                break

            params = {"page": next_page}
        print(all_wbs)
        return all_wbs

    @validate_params("workspace_name")
    def list_workbooks_in_workspace(self, workspace_name: str, tags: List[str]) -> List[Dict]:
        """
        Get all available Sigma workbooks for a given workspace.

        :param workspace_name: The name of a given workspace.
        :type workspace_name: str

        Returns:
            List[Dict]: A list of workbooks in the workspace.
        """
        workbooks = self.get_workbooks()
        workbook_list = [wb for wb in workbooks if wb['path'].startswith(workspace_name)]

        verified_list = []
        for wb in workbook_list:
            if self.verify_tags(wb["workbookId"], tags)["is_verified"]:
                verified_list.append(wb)
        
        return verified_list

    @validate_params("workbook_id")
    def get_embed_for_dashboard(self, workbook_id: str) -> str:
        """
        Gets the embed information from Sigma for a specific workbook.

        :param workbook_id: The ID of the workbook in Sigma.
        :type workbook_id: str

        Returns:
            str: The embed URL.
        Raises:
            ServiceError: Returns a 404 if the workbook can't be found.
        """
        response = self._safe_get(
            build_url(SIGMA_BASE_URL, WORKBOOKS, workbook_id, EMBEDS),
            headers=get_headers(SIGMA_TOKEN),
        )
        data = process_response(response)

        if data["entries"]:
            return data["entries"][0]
        else:
            return self.create_embed(workbook_id=workbook_id)

    @validate_params("workbook_id")
    def create_embed(self, workbook_id: str) -> int:
        """
        Creates the embed object on the Sigma server.

        :param workbook_id: The ID of the workbook that needs to be embedded.
        :type workbook_id: str

        Returns:
            int: The HTTP status code of the response if successful.
        Raises:
            ServiceError: If the creation was unsuccessful.
        """
        body = {
            "embedType": "secure",
            "sourceType": "workbook"
        }
        
        response = self._safe_post(
            build_url(SIGMA_BASE_URL, WORKBOOKS, workbook_id, EMBEDS),
            json=body,
            headers=get_headers(SIGMA_TOKEN),
        )
        process_response(response)
        return response.status_code

    def get_workbook(self, workbook_id: str) -> dict:
        response = self._safe_get(
            build_url(SIGMA_BASE_URL, WORKBOOKS, workbook_id),
            headers=get_headers(SIGMA_TOKEN),
        )
        return process_response(response)

    @validate_params("dashboard_id", "user_id", "workspace_id")
    def create_embed_url(self, dashboard_id: str, user_id: str, workspace_id: str) -> Dict[str, str]:
        """
        Generates the URL for the embedded dashboard.

        :param dashboard_id: The ID of the dashboard (Sigma workbook).
        :type dashboard_id: str

        Returns:
            Dict[str, str]: A dictionary containing the parameterized embed URL.
        Raises:
            ServiceError: If the call to retrieve the embed code fails.
        """

        workspace_service = WorkspaceService()
        workspace = Workspace(**workspace_service.get_workspace(workspace_id))

        user_service = UserService()
        user = user_service.get_user(user_id)

        if not user or not workspace:
            raise ServiceError("Could not retrieve information", 500)

        connection_service = ConnectionService()
        connections = connection_service.get_connection_by_host(urlparse(workspace.server).netloc)
    
        if not connections:
            print("Not good")
            ##create one    
            pass

        connection = Connection(**connections[0])

        workbook = self.get_workbook(dashboard_id)

        if workbook:
            dashboard_id = workbook.get("workbookUrlId")

        nonce = str(uuid.uuid4())
        timestamp = int(time.time())
        exp = int(time.time()) + 1800

        email = None

        if "kytheralabs.com" in user.email:
            email = f"{user.first_name}.{user.last_name}@kytherlabstest.com"
        else:
            email = user.email


        jwt_claim = SigmaClaim(
            sub=email, 
            iss=SIGMA_JWT_CLIENT_ID, 
            jti=nonce, 
            iat=timestamp, 
            exp=exp, 
            eval_connection_id=connection.connection_id,
            teams=["all_clients_team"],
            ).model_dump(exclude_none=True)
        
        token = jwt.encode(
            payload=jwt_claim, 
            key=SIGMA_JWT_CLIENT_SECRET, 
            algorithm=JWT_ALGORITHM, 
            headers={"kid": SIGMA_JWT_CLIENT_ID})

        pBuilder = ParamBuilder()
        (pBuilder
            .add_param("jwt", token, True)
            .add_param("embed", True)
            .add_param("hide_bookmarks", "true")
            .add_param("hide_folder_navigation", "true")
            .add_param("hide_menu", "true")
            .add_param("ua_catalog", "luminis"))


        url = f"{build_url(SIGMA_JWT_BASE_URL, "workbook", dashboard_id)}{pBuilder.get_query_string()}"
        logger.info(f"The embedded URL for {dashboard_id}: {url}")

        return {"embed_url": url}

    def get_tags(self) -> Dict:
        """
        Gets all the tags from the Sigma Server

        Returns:
            List[Dict[string, any]]: A list of tags
        Raises:
            ServiceError: If the call to Sigma was unsuccessful.
        """
    
        response = self._safe_get(
            build_url(SIGMA_BASE_URL, SIGMA_TAG_URL),
            headers=get_headers(SIGMA_TOKEN),
        )
        return process_response(response)
    
    @validate_params("name")
    def get_tags_by_name(self, name: str) -> Dict:
        """
        Gets all the tags from the Sigma Server and filters them out by the given name

        Returns:
            List[Dict[string, any]]: A list of tags
        Raises:
            ServiceError: If the call to Sigma was unsuccessful.
        """

        tags = self.get_tags()["entries"]

        return [tag for tag in tags if tag['name'].startswith(name)]
    
    @validate_params("workbook_id")
    def verify_tags(self, workbook_id: str, tags: List[str]) -> Dict:
        """
        Gets all the tags for the workbook from the server

        Returns:
            List[Dict[string, any]]: A list of tags
        Raises:
            ServiceError: If the call to Sigma was unsuccessful.
        """

        tag_list = []

        for tag in tags:
            listOfTags = self.get_tags_by_name(tag)

            for lt in listOfTags:
                tag_list.append(lt["versionTagId"])
        
        is_verified_list = []
        for tag in tag_list:
            response = self._safe_get(
                build_url(SIGMA_BASE_URL, SIGMA_TAG_URL, tag, "workbooks"),
                headers=get_headers(SIGMA_TOKEN),
            )
            logger.info(process_response(response))
            data = process_response(response)["entries"]
            is_verified = any(w['workbookId'] == workbook_id for w in data)
            is_verified_list.append(is_verified)

    
        return {"workbook_id": workbook_id, "is_verified": all(is_verified_list)}
    
    @validate_params("workbook_id")
    def share_workbook(self, workbook_id: str):
        payload = {
             "grants": [{"grantee":{"teamId": TEAM_ID}, "permission": "view"}]}
        return self._safe_post(
            build_url(SIGMA_BASE_URL, WORKBOOKS, workbook_id, "grants"),
            payload,
            headers=get_headers(SIGMA_TOKEN),
        )
