from __future__ import annotations

import hashlib
import secrets
from datetime import date, datetime
from typing import Any, Dict, Optional

from app.exceptions.forge_error import ForgeError
from app.repositories.mcp_oauth import MCPAppClientRepository, MCPPrincipalGrantRepository

MCP_APP_PRINCIPAL_ALLOWED_TOOLS = [
    "search_domains",
    "get_domain_profile",
    "search_dictionary",
    "plan_query",
    "validate_query_plan",
    "compile_query",
    "preview_query",
    "list_saved_queries",
    "run_saved_query",
]


def _secret_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _trim(value: Any) -> str:
    return str(value or "").strip()


def _bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = value.replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raise ForgeError("Expected a list value.", status_code=400)
    seen: set[str] = set()
    result: list[str] = []
    for item in raw_items:
        normalized = _trim(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _optional_list(value: Any) -> Optional[list[str]]:
    items = _list(value)
    return items or None


def _preview_limit(value: Any) -> int:
    try:
        limit = int(value or 100)
    except (TypeError, ValueError):
        raise ForgeError("preview_row_limit must be an integer.", status_code=400)
    if limit < 1 or limit > 500:
        raise ForgeError("preview_row_limit must be between 1 and 500.", status_code=400)
    return limit


class MCPAppPrincipalService:
    def __init__(
        self,
        *,
        clients: Optional[MCPAppClientRepository] = None,
        grants: Optional[MCPPrincipalGrantRepository] = None,
    ) -> None:
        self._clients = clients or MCPAppClientRepository()
        self._grants = grants or MCPPrincipalGrantRepository()

    def list_principals(self, *, workspace_id: str) -> Dict[str, Any]:
        workspace = self._workspace(workspace_id)
        return {
            "workspace_id": workspace,
            "items": [self._serialize_client(row) for row in self._clients.list_workspace_clients(workspace_id=workspace)],
        }

    def create_principal(self, *, workspace_id: str, actor_user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        workspace = self._workspace(workspace_id)
        display_name = _trim(payload.get("display_name"))
        if not display_name:
            raise ForgeError("display_name is required.", status_code=400)

        allowed_tools = _optional_list(payload.get("allowed_tools"))
        if allowed_tools:
            unsupported = [tool for tool in allowed_tools if tool not in MCP_APP_PRINCIPAL_ALLOWED_TOOLS]
            if unsupported:
                raise ForgeError(
                    "Unsupported MCP tool requested.",
                    status_code=400,
                    details={"unsupported_tools": unsupported},
                )

        client_id = f"qf_app_{secrets.token_urlsafe(18)}"
        client_secret = f"qf_app_secret_{secrets.token_urlsafe(32)}"
        self._clients.create_client(
            payload={
                "client_id": client_id,
                "client_secret_hash": _secret_hash(client_secret),
                "display_name": display_name,
                "description": _trim(payload.get("description")) or None,
                "owning_workspace_id": workspace,
                "owner_user_id": _trim(payload.get("owner_user_id")) or None,
                "created_by": _trim(actor_user_id) or None,
                "expires_at": _trim(payload.get("expires_at")) or None,
            }
        )
        grant = self._grants.upsert_app_grant(
            principal_id=client_id,
            workspace_id=workspace,
            enabled=True,
            allowed_tools=allowed_tools,
            allowed_domain_keys=_optional_list(payload.get("allowed_domain_keys")),
            can_preview=_bool(payload.get("can_preview"), default=False),
            preview_row_limit=_preview_limit(payload.get("preview_row_limit")),
            created_by=actor_user_id,
            expires_at=_trim(payload.get("grant_expires_at") or payload.get("expires_at")) or None,
        )
        client = self._clients.get_client(client_id=client_id, workspace_id=workspace) or {
            "client_id": client_id,
            "display_name": display_name,
            "description": _trim(payload.get("description")) or None,
            "owning_workspace_id": workspace,
            "created_by": _trim(actor_user_id) or None,
            "expires_at": _trim(payload.get("expires_at")) or None,
            "revoked_at": None,
        }
        return {
            "workspace_id": workspace,
            "client_secret": client_secret,
            "item": self._serialize_client({**client, **self._grant_to_row(grant)}),
        }

    def revoke_principal(self, *, workspace_id: str, client_id: str) -> Dict[str, Any]:
        workspace = self._workspace(workspace_id)
        client = self._clients.get_client(client_id=client_id, workspace_id=workspace)
        if not client:
            raise ForgeError("MCP app principal not found.", status_code=404)
        self._grants.revoke_app_grant(principal_id=client_id, workspace_id=workspace)
        self._clients.revoke_client(client_id=client_id, workspace_id=workspace)
        refreshed = self._clients.get_client(client_id=client_id, workspace_id=workspace) or client
        grant = self._grants.get_app_grant(principal_id=client_id, workspace_id=workspace) or {}
        return {"workspace_id": workspace, "item": self._serialize_client({**refreshed, **self._grant_to_row(grant)})}

    def _workspace(self, workspace_id: str) -> str:
        workspace = _trim(workspace_id)
        if not workspace:
            raise ForgeError("workspace_id is required.", status_code=400)
        return workspace

    def _serialize_client(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "client_id": _trim(row.get("client_id")),
            "display_name": _trim(row.get("display_name")),
            "description": _trim(row.get("description")) or None,
            "owning_workspace_id": _trim(row.get("owning_workspace_id")),
            "owner_user_id": _trim(row.get("owner_user_id")) or None,
            "created_by": _trim(row.get("created_by")) or None,
            "created_at": _iso(row.get("created_at")),
            "last_used_at": _iso(row.get("last_used_at")),
            "expires_at": _iso(row.get("expires_at")),
            "revoked_at": _iso(row.get("revoked_at")),
            "rotation_required_at": _iso(row.get("rotation_required_at")),
            "grant": {
                "enabled": _bool(row.get("grant_enabled"), default=False),
                "allowed_tools": _list(row.get("allowed_tools")),
                "allowed_domain_keys": _list(row.get("allowed_domain_keys")),
                "can_preview": _bool(row.get("can_preview"), default=False),
                "preview_row_limit": _preview_limit(row.get("preview_row_limit")),
                "expires_at": _iso(row.get("grant_expires_at")),
                "revoked_at": _iso(row.get("grant_revoked_at")),
                "updated_at": _iso(row.get("grant_updated_at")),
            },
        }

    def _grant_to_row(self, grant: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "grant_enabled": grant.get("enabled"),
            "allowed_tools": grant.get("allowed_tools"),
            "allowed_domain_keys": grant.get("allowed_domain_keys"),
            "can_preview": grant.get("can_preview"),
            "preview_row_limit": grant.get("preview_row_limit"),
            "grant_expires_at": grant.get("expires_at"),
            "grant_revoked_at": grant.get("revoked_at"),
            "grant_updated_at": grant.get("updated_at"),
        }


__all__ = ["MCP_APP_PRINCIPAL_ALLOWED_TOOLS", "MCPAppPrincipalService"]
