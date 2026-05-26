from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from app.config.mcp_oauth_config import MCPOAuthConfig, load_mcp_oauth_config
from app.exceptions.forge_error import ForgeError
from app.repositories.mcp_oauth import MCPPrincipalGrantRepository, WorkspaceMCPSettingsRepository


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MCPOAuthAccessService:
    def __init__(
        self,
        *,
        config_loader: Callable[[], MCPOAuthConfig] = load_mcp_oauth_config,
        workspace_settings_repository: WorkspaceMCPSettingsRepository | None = None,
        principal_grant_repository: MCPPrincipalGrantRepository | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._config_loader = config_loader
        self._workspace_settings = workspace_settings_repository or WorkspaceMCPSettingsRepository()
        self._principal_grants = principal_grant_repository or MCPPrincipalGrantRepository()
        self._now_provider = now_provider or _utc_now

    def assert_mcp_enabled(self, *, workspace_id: str) -> dict[str, Any]:
        config = self._config_loader()
        if not config.mcp_enabled:
            raise ForgeError("QueryForge MCP is disabled by runtime configuration", status_code=403)

        settings = self._workspace_settings.get_settings(workspace_id=workspace_id)
        if config.mcp_require_workspace_enablement and not bool(settings.get("enabled")):
            raise ForgeError("QueryForge MCP is not enabled for this workspace", status_code=403)
        return settings

    def get_app_grant(self, *, principal_type: str, principal_id: str, workspace_id: str) -> dict[str, Any] | None:
        return self._principal_grants.get_active_grant(
            principal_type=principal_type,
            principal_id=principal_id,
            workspace_id=workspace_id,
            now=self._now_provider(),
        )


__all__ = ["MCPOAuthAccessService"]
