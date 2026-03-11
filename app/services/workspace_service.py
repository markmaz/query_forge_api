from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import DATABRICKS_WORKSPACE_USERS_URL
from app.decorators.validate import validate_params
from app.exceptions.forge_error import ForgeError
from app.models.user import User
from app.models.workspace import Workspace
from app.ports.sql_executor import ForgeQueryPort
from app.services.base_service import build_url, process_response
from app.services.tenancy.datasource_resolver_service import WorkspaceDatasourceResolverService
from app.services.tenancy.secret_resolver import SecretResolver
from app.services.workspace_user_read_service import WorkspaceUserReadService

logger = logging.getLogger(__name__)

_DBX_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class _WorkspaceRow:
    workspace_id: str
    workspace_name: str
    deployment_name: str = ""


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
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None):
        self._sql = sql or ForgeMetaSQL()
        self._resolver = WorkspaceDatasourceResolverService(sql=self._sql)
        self._secrets = SecretResolver()
        self._workspace_users = WorkspaceUserReadService(sql=self._sql)

    def get_all_workspaces(self) -> list[dict[str, str]]:
        rows = self._list_workspace_rows()
        return [self._workspace_payload_from_row(r) for r in rows]

    @validate_params("workspace_id")
    def get_workspace_users_from_dbx(self, workspace_id: str) -> list[dict[str, str]]:
        try:
            resolved = self._resolver.resolve_for_workspace(workspace_id=str(workspace_id), require_active=True)
        except ForgeError as exc:
            logger.error("Workspace not found. workspace_id=%s", workspace_id)
            raise ForgeError(f"Workspace {workspace_id} not found", status_code=404) from exc

        if not resolved or str(resolved.datasource_type or "").strip().lower() != "databricks":
            return self._workspace_users.list_workspace_users(
                workspace_id=str(workspace_id),
                include_inactive=False,
            )

        cfg = dict(resolved.config_json or {})
        host = str(cfg.get("host") or cfg.get("workspace_url") or cfg.get("server") or "").strip()
        token = str(cfg.get("token") or "").strip()
        if not token:
            token = str(self._secrets.resolve(resolved.secret_ref) or "").strip()

        if not host:
            raise ForgeError(
                f"Workspace {workspace_id} has no Databricks host configured in datasource config_json",
                status_code=400,
            )
        if not token:
            raise ForgeError(
                f"Workspace {workspace_id} Databricks datasource is missing token/secret_ref",
                status_code=503,
            )

        response = requests.get(
            build_url(host, DATABRICKS_WORKSPACE_USERS_URL),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=_DBX_TIMEOUT_SECONDS,
        )
        payload = process_response(response)
        members = payload.get("Resources", []) if isinstance(payload, dict) else []

        org_name = str(self.get_workspace(workspace_id).get("name") or "")
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
        ws = str(workspace_id or "").strip()
        if not ws:
            raise ForgeError("workspace_id is required", status_code=400)
        rows = self._list_workspace_rows(workspace_id=ws)
        if not rows:
            raise ForgeError(f"Workspace {ws} not found", status_code=404)
        return self._workspace_payload_from_row(rows[0])

    def _list_workspace_rows(self, *, workspace_id: Optional[str] = None) -> list[dict[str, Any]]:
        params: Dict[str, Any] = {"workspace_id": workspace_id}
        try:
            return self._sql.execute_query_mappings(
                """
                SELECT
                  w.id AS workspace_id,
                  COALESCE(NULLIF(w.name, ''), w.id) AS workspace_name,
                  d.type AS datasource_type,
                  d.config_json AS datasource_config_json
                FROM workspace w
                LEFT JOIN datasource d ON d.id = w.datasource_id
                WHERE (:workspace_id IS NULL OR w.id = :workspace_id)
                ORDER BY w.id
                """,
                params,
            )
        except Exception:
            # Backward compatibility for environments without tenancy columns.
            legacy_rows = self._sql.execute_query_mappings(
                """
                SELECT
                  w.id AS workspace_id,
                  COALESCE(NULLIF(w.display_name, ''), w.id) AS workspace_name,
                  w.server AS server
                FROM workspace w
                WHERE (:workspace_id IS NULL OR w.id = :workspace_id)
                ORDER BY w.id
                """,
                params,
            )
            out: list[dict[str, Any]] = []
            for row in legacy_rows:
                row_map = dict(row)
                out.append(
                    {
                        "workspace_id": row_map.get("workspace_id"),
                        "workspace_name": row_map.get("workspace_name"),
                        "datasource_type": None,
                        "datasource_config_json": {"host": row_map.get("server")},
                    }
                )
            return out

    def _workspace_payload_from_row(self, row: dict[str, Any]) -> dict[str, str]:
        config = _coerce_json_obj(row.get("datasource_config_json"))
        server = _derive_server_url(
            datasource_type=str(row.get("datasource_type") or "").strip().lower(),
            config_json=config,
        )
        payload = {
            "workspace_id": str(row.get("workspace_id") or ""),
            "workspace_name": str(row.get("workspace_name") or row.get("workspace_id") or ""),
            "deployment_name": server or "",
        }
        return _as_workspace(payload).model_dump()


def _coerce_json_obj(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if value is None:
        return {}
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="ignore")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _derive_server_url(*, datasource_type: str, config_json: Dict[str, Any]) -> str:
    explicit = (
        config_json.get("external_url")
        or config_json.get("console_url")
        or config_json.get("web_url")
    )
    if explicit:
        return _normalize_url(str(explicit))

    generic_host = str(config_json.get("host") or config_json.get("workspace_url") or config_json.get("server") or "").strip()
    if generic_host and datasource_type != "snowflake":
        return _normalize_url(generic_host)

    if datasource_type == "databricks":
        return _normalize_url(str(config_json.get("host") or config_json.get("workspace_url") or config_json.get("server") or ""))

    if datasource_type == "snowflake":
        host = str(config_json.get("host") or config_json.get("account_url") or "").strip()
        if host:
            return _normalize_url(host)
        account = str(config_json.get("account") or "").strip()
        if not account:
            return ""
        return _normalize_url(account if account.startswith(("http://", "https://")) else f"https://{account}.snowflakecomputing.com")

    return ""


def _normalize_url(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return value.rstrip("/")
