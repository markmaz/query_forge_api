from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

from app.config import DATABRICKS_BASE_ACCOUNT_URL, DATABRICKS_WORKSPACE_USERS_URL, DATABRICKS_WORKSPACES
from app.decorators.validate import validate_params
from app.exceptions.forge_error import ForgeError
from app.models.user import User
from app.models.workspace import Workspace
from app.services.base_service import build_url, process_response
from app.services.base_token_manager import QF_DATABRICKS_TOKEN, forge_auth_headers

logger = logging.getLogger(__name__)

_DBX_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class _WorkspaceRow:
    workspace_id: str
    workspace_name: str
    deployment_name: str


def _as_workspace(row: dict[str, Any]) -> Workspace:
    parsed = _WorkspaceRow(
        workspace_id=str(row.get("workspace_id") or ""),
        workspace_name=str(row.get("workspace_name") or ""),
        deployment_name=str(row.get("deployment_name") or ""),
    )
    return Workspace(
        workspace_id=parsed.workspace_id,
        name=parsed.workspace_name,
        server=parsed.deployment_name,
    )


class WorkspaceService:
    def get_all_workspaces(self) -> list[dict[str, str]]:
        response = requests.get(
            build_url(DATABRICKS_BASE_ACCOUNT_URL, DATABRICKS_WORKSPACES),
            headers=forge_auth_headers(QF_DATABRICKS_TOKEN),
            timeout=_DBX_TIMEOUT_SECONDS,
        )
        payload = process_response(response)
        if not isinstance(payload, list):
            return []
        return [_as_workspace(item).model_dump() for item in payload]

    @validate_params("workspace_id")
    def get_workspace_users_from_dbx(self, workspace_id: str) -> list[dict[str, str]]:
        try:
            workspace = self.get_workspace(workspace_id)
        except ForgeError as exc:
            logger.error("Workspace not found. workspace_id=%s", workspace_id)
            raise ForgeError(f"Workspace {workspace_id} not found", status_code=404) from exc

        response = requests.get(
            build_url(workspace["server"], DATABRICKS_WORKSPACE_USERS_URL),
            headers=forge_auth_headers(QF_DATABRICKS_TOKEN),
            timeout=_DBX_TIMEOUT_SECONDS,
        )
        payload = process_response(response)
        members = payload.get("Resources", []) if isinstance(payload, dict) else []

        org_name = str(workspace.get("name") or "")
        users: list[dict[str, str]] = []
        for member in members:
            given = str((member.get("name") or {}).get("givenName") or "")
            family = str((member.get("name") or {}).get("familyName") or "")
            profile = User(
                first_name=given,
                last_name=family,
                organization=org_name,
                display_name=str(member.get("displayName") or ""),
                user_name=str(member.get("userName") or ""),
            )
            users.append(profile.model_dump(mode="json"))
        return users

    @validate_params("workspace_id")
    def get_workspace(self, workspace_id: str) -> dict[str, str]:
        logger.debug("Fetching workspace metadata for workspace_id=%s", workspace_id)
        response = requests.get(
            build_url(DATABRICKS_BASE_ACCOUNT_URL, DATABRICKS_WORKSPACES, workspace_id),
            headers=forge_auth_headers(QF_DATABRICKS_TOKEN),
            timeout=_DBX_TIMEOUT_SECONDS,
        )
        payload = process_response(response)
        if not isinstance(payload, dict):
            raise ForgeError("Workspace payload is invalid", status_code=502)
        return _as_workspace(payload).model_dump()
