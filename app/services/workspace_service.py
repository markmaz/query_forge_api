from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.models.tenancy.workspace import Workspace
from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)


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

    def get_all_workspaces(self) -> list[dict[str, str]]:
        rows = self._list_workspace_rows()
        return [self._workspace_payload_from_row(r) for r in rows]

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
        except (TypeError, ValueError, json.JSONDecodeError):
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
