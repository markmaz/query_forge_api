import logging
import os
from typing import Any, Mapping, Optional

from dotenv import load_dotenv

from app.adapters.base_token_manager import BaseForgeTokenManager
from app.services.base_service import build_url

logger = logging.getLogger(__name__)
_DEFAULT_DATABRICKS_WORKSPACE_TOKEN_PATH = "oidc/v1/token"


class DatabricksWorkspaceTokenProvider(BaseForgeTokenManager):
    def __init__(
        self,
        workspace_host: str,
        workspace_id: str,
        *,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        token_path: Optional[str] = None,
        token_url: Optional[str] = None,
        scope: str = "all-apis",
        manager_name: str = "DATABRICKS_WORKSPACE_TOKEN_MANAGER",
    ):
        load_dotenv()

        self._workspace_host = workspace_host
        resolved_token_url = _resolve_token_url(
            workspace_host=workspace_host,
            token_path=token_path,
            token_url=token_url,
        )
        resolved_client_id = str(client_id or os.getenv("DATABRICKS_CLIENT_ID") or "").strip()
        resolved_client_secret = str(client_secret or os.getenv("DATABRICKS_CLIENT_SECRET") or "").strip()
        if not resolved_client_id or not resolved_client_secret:
            raise ValueError(
                "Databricks OAuth requires client_id and client_secret"
            )

        logger.info("Databricks token provider initialised for host=%s token_url=%s", workspace_host, resolved_token_url)

        super().__init__(
            manager_name,
            resolved_token_url,
            resolved_client_id,
            resolved_client_secret,
            scope=scope,
        )

    def refresh_token(self):
        super().refresh_token()
        if self._token:
            logger.info(
                "Workspace token refreshed for Databricks host: %s",
                self._workspace_host,
            )


def create_databricks_oauth_provider(
    *,
    workspace_host: str,
    workspace_id: str,
    config: Mapping[str, Any] | None,
) -> Optional[DatabricksWorkspaceTokenProvider]:
    cfg = dict(config or {})
    auth_method = str(cfg.get("auth_method") or "").strip().lower()
    if auth_method != "oauth_client_credentials":
        return None

    return DatabricksWorkspaceTokenProvider(
        workspace_host=workspace_host,
        workspace_id=workspace_id,
        client_id=str(cfg.get("client_id") or "").strip() or None,
        client_secret=str(cfg.get("client_secret") or "").strip() or None,
        token_path=str(cfg.get("token_path") or "").strip() or None,
        token_url=str(cfg.get("token_url") or "").strip() or None,
        scope=str(cfg.get("oauth_scope") or "all-apis").strip() or "all-apis",
        manager_name="DATABRICKS_DATASOURCE_TOKEN_MANAGER",
    )


def _resolve_token_url(
    *,
    workspace_host: str,
    token_path: Optional[str],
    token_url: Optional[str],
) -> str:
    explicit_url = str(token_url or "").strip()
    if explicit_url:
        return explicit_url

    path = (
        str(token_path or "").strip()
        or str(os.getenv("DATABRICKS_WORKSPACE_TOKEN_URL") or "").strip()
        or _DEFAULT_DATABRICKS_WORKSPACE_TOKEN_PATH
    )
    return build_url(workspace_host, path) or ""
