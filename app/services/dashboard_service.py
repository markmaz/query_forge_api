from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any
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
from app.exceptions.forge_error import ForgeError
from app.models.connection import Connection
from app.models.sigma_claim import SigmaClaim
from app.models.workspace import Workspace
from app.services.base_service import build_url, process_response
from app.services.base_token_manager import QF_SIGMA_TOKEN, forge_auth_headers
from app.services.connection_service import ConnectionService
from app.services.user_service import UserService
from app.services.workspace_service import WorkspaceService
from app.utils.param_builder import SigmaEmbedParams

logger = logging.getLogger(__name__)

_WORKSPACES_PATH = "workspaces"
_WORKBOOKS_PATH = "workbooks"
_EMBEDS_PATH = "embeds"
_SIGMA_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class _EmbedLookup:
    workspace: Workspace
    connection: Connection
    user_email: str
    user_first_name: str
    user_last_name: str
    dashboard_url_id: str


class _SigmaGateway:
    def __init__(self) -> None:
        self._headers = forge_auth_headers(QF_SIGMA_TOKEN)

    def request(
        self,
        method: str,
        *path_parts: str,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        url = build_url(SIGMA_BASE_URL, *path_parts)
        try:
            response = requests.request(
                method,
                url,
                headers=self._headers,
                params=params,
                json=payload,
                timeout=_SIGMA_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise ForgeError("Sigma API unavailable", status_code=424) from exc
        return response


class DashboardService:
    def __init__(self) -> None:
        self._sigma = _SigmaGateway()

    def get_workspaces(self) -> list[dict[str, Any]]:
        response = self._sigma.request("GET", _WORKSPACES_PATH)
        payload = process_response(response)
        if isinstance(payload, list):
            return payload
        return payload.get("entries") or []

    def get_workbooks(self) -> list[dict[str, Any]]:
        page_cursor: str | None = None
        collected: list[dict[str, Any]] = []

        while True:
            params = {"page": page_cursor} if page_cursor else None
            response = self._sigma.request("GET", _WORKBOOKS_PATH, params=params)
            response.raise_for_status()
            body = response.json()
            collected.extend(body.get("entries") or [])
            page_cursor = body.get("nextPage")
            if not page_cursor:
                break

        logger.debug("Fetched %s Sigma workbooks", len(collected))
        return collected

    @validate_params("workspace_name")
    def list_workbooks_in_workspace(self, workspace_name: str, tags: list[str]) -> list[dict[str, Any]]:
        candidates = [
            workbook
            for workbook in self.get_workbooks()
            if str(workbook.get("path") or "").startswith(workspace_name)
        ]
        return [
            workbook
            for workbook in candidates
            if self.verify_tags(str(workbook.get("workbookId")), tags).get("is_verified")
        ]

    @validate_params("workbook_id")
    def get_embed_for_dashboard(self, workbook_id: str) -> str:
        response = self._sigma.request("GET", _WORKBOOKS_PATH, workbook_id, _EMBEDS_PATH)
        payload = process_response(response)
        entries = payload.get("entries") or []
        if entries:
            return entries[0]
        self.create_embed(workbook_id=workbook_id)
        response_retry = self._sigma.request("GET", _WORKBOOKS_PATH, workbook_id, _EMBEDS_PATH)
        retry_payload = process_response(response_retry)
        retry_entries = retry_payload.get("entries") or []
        if not retry_entries:
            raise ForgeError("Could not create Sigma embed", status_code=502)
        return retry_entries[0]

    @validate_params("workbook_id")
    def create_embed(self, workbook_id: str) -> int:
        response = self._sigma.request(
            "POST",
            _WORKBOOKS_PATH,
            workbook_id,
            _EMBEDS_PATH,
            payload={"embedType": "secure", "sourceType": "workbook"},
        )
        process_response(response)
        return int(response.status_code)

    def get_workbook(self, workbook_id: str) -> dict[str, Any]:
        response = self._sigma.request("GET", _WORKBOOKS_PATH, workbook_id)
        payload = process_response(response)
        if not isinstance(payload, dict):
            raise ForgeError("Invalid Sigma workbook response", status_code=502)
        return payload

    @validate_params("dashboard_id", "user_id", "workspace_id")
    def create_embed_url(self, dashboard_id: str, user_id: str, workspace_id: str) -> dict[str, str]:
        embed_lookup = self._resolve_embed_lookup(
            dashboard_id=dashboard_id,
            user_id=user_id,
            workspace_id=workspace_id,
        )
        jwt_token = self._build_embed_jwt(
            email=self._embed_email(
                embed_lookup.user_email,
                embed_lookup.user_first_name,
                embed_lookup.user_last_name,
            ),
            connection_id=embed_lookup.connection.connection_id,
        )

        query = (
            SigmaEmbedParams()
            .add_param("jwt", jwt_token, True)
            .add_param("embed", True)
            .add_param("hide_bookmarks", "true")
            .add_param("hide_folder_navigation", "true")
            .add_param("hide_menu", "true")
            .add_param("ua_catalog", "luminis")
            .get_query_string()
        )

        base = build_url(SIGMA_JWT_BASE_URL, "workbook", embed_lookup.dashboard_url_id)
        logger.info(
            "Generated Sigma embed URL dashboard_url_id=%s host=%s",
            embed_lookup.dashboard_url_id,
            urlparse(base).netloc,
        )
        return {"embed_url": f"{base}{query}"}

    def get_tags(self) -> dict[str, Any]:
        response = self._sigma.request("GET", SIGMA_TAG_URL)
        payload = process_response(response)
        if not isinstance(payload, dict):
            raise ForgeError("Invalid Sigma tags response", status_code=502)
        return payload

    @validate_params("name")
    def get_tags_by_name(self, name: str) -> list[dict[str, Any]]:
        entries = self.get_tags().get("entries") or []
        return [tag for tag in entries if str(tag.get("name") or "").startswith(name)]

    @validate_params("workbook_id")
    def verify_tags(self, workbook_id: str, tags: list[str]) -> dict[str, Any]:
        if not tags:
            return {"workbook_id": workbook_id, "is_verified": True}

        version_tag_ids = [
            str(tag.get("versionTagId"))
            for tag_name in tags
            for tag in self.get_tags_by_name(tag_name)
            if tag.get("versionTagId")
        ]

        if not version_tag_ids:
            return {"workbook_id": workbook_id, "is_verified": False}

        has_all_tags = True
        for version_tag_id in version_tag_ids:
            response = self._sigma.request("GET", SIGMA_TAG_URL, version_tag_id, _WORKBOOKS_PATH)
            payload = process_response(response)
            entries = payload.get("entries") or []
            matches = any(str(entry.get("workbookId")) == workbook_id for entry in entries)
            if not matches:
                has_all_tags = False
                break

        return {"workbook_id": workbook_id, "is_verified": has_all_tags}

    def _resolve_embed_lookup(self, dashboard_id: str, user_id: str, workspace_id: str) -> _EmbedLookup:
        workspace_payload = WorkspaceService().get_workspace(workspace_id)
        user = UserService().get_user(user_id)
        if not workspace_payload or not user:
            raise ForgeError("Could not retrieve information", status_code=500)

        workspace = Workspace(**workspace_payload)
        workspace_host = urlparse(workspace.server).netloc
        candidates = ConnectionService().get_connection_by_host(workspace_host)
        if not candidates:
            raise ForgeError("No Sigma connection configured for workspace", status_code=404)

        workbook = self.get_workbook(dashboard_id)
        dashboard_url_id = str(workbook.get("workbookUrlId") or dashboard_id)
        return _EmbedLookup(
            workspace=workspace,
            connection=Connection(**candidates[0]),
            user_email=str(user.email),
            user_first_name=str(user.first_name or ""),
            user_last_name=str(user.last_name or ""),
            dashboard_url_id=dashboard_url_id,
        )

    def _build_embed_jwt(self, *, email: str, connection_id: str) -> str:
        issued_at = int(time.time())
        claim = SigmaClaim(
            sub=email,
            iss=SIGMA_JWT_CLIENT_ID,
            jti=str(uuid.uuid4()),
            iat=issued_at,
            exp=issued_at + 1800,
            eval_connection_id=connection_id,
            teams=["all_clients_team"],
        ).model_dump(exclude_none=True)

        return jwt.encode(
            payload=claim,
            key=SIGMA_JWT_CLIENT_SECRET,
            qf_algorithm=JWT_ALGORITHM,
            headers={"kid": SIGMA_JWT_CLIENT_ID},
        )

    def _embed_email(self, email: str, first_name: str, last_name: str) -> str:
        if "kytheralabs.com" in (email or ""):
            return f"{first_name}.{last_name}@kytherlabstest.com"
        return email
