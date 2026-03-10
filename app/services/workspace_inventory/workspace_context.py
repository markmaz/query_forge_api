from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from flask import g, has_request_context

from app.adapters.databricke_workspace_token_manager import DatabricksWorkspaceForgeTokenPort
from app.adapters.databricks_sql_executor import DatabricksForgeQueryPort
from app.config import DEFAULT_SQL_WAREHOUSE
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.analytics.executor_adapter import AnalyticsExecutorForgeAdapter
from app.services.analytics.executor_factory import ExecutorFactory
from app.services.shared.request_context import resolve_request_username
from app.services.tenancy.datasource_resolver_service import (
    ResolvedWorkspaceDatasource,
    WorkspaceDatasourceResolverService,
)
from app.services.tenancy.secret_resolver import SecretResolver
from app.services.workspace_access_service import WorkspaceAccessService
from app.services.warehouse_service import WarehouseService
from app.services.workspace_service import WorkspaceService


class _StaticTokenProvider:
    def __init__(self, token: str):
        self._token = str(token or "").strip()

    @property
    def token(self) -> str:
        return self._token


@dataclass(frozen=True)
class CatalogContext:
    workspace_id: str
    workspace_url: str
    warehouse_id: str
    user_name: str
    sql_exec: ForgeQueryPort


class WorkspaceContextBuilder:
    """
    Mirrors your ValueOverride pattern, but for catalog admin.
    """

    def build(self, workspace_id: str) -> CatalogContext:
        workspace_id = str(workspace_id or "").strip()
        if not workspace_id:
            raise ForgeError("workspace_id is required", status_code=400)

        self._assert_request_workspace_access(workspace_id)

        user_name = resolve_request_username()

        resolved = self._try_resolve_workspace_datasource(workspace_id)
        if resolved is not None:
            return self._build_from_datasource(workspace_id=workspace_id, resolved=resolved, user_name=user_name)

        workspace_url = self._resolve_workspace_url(workspace_id)
        warehouse_id = self._resolve_default_warehouse_id(workspace_id)
        token_manager = DatabricksWorkspaceForgeTokenPort(workspace_host=workspace_url, workspace_id=workspace_id)
        sql_exec: ForgeQueryPort = DatabricksForgeQueryPort(
            base_url=workspace_url,
            token_provider=token_manager,
            default_warehouse_id=warehouse_id,
        )

        return CatalogContext(
            workspace_id=workspace_id,
            workspace_url=workspace_url,
            warehouse_id=warehouse_id,
            user_name=user_name,
            sql_exec=sql_exec,
        )

    def _try_resolve_workspace_datasource(self, workspace_id: str) -> Optional[ResolvedWorkspaceDatasource]:
        try:
            return WorkspaceDatasourceResolverService().resolve_for_workspace(
                workspace_id=workspace_id,
                require_active=True,
            )
        except ForgeError as exc:
            if exc.status_code in (404,):
                # Backward compatibility for environments that have not migrated
                # workspaces into the tenancy tables yet.
                return None
            raise
        except Exception:
            # Missing migration/table should not break legacy operation.
            return None

    def _build_from_datasource(
        self,
        *,
        workspace_id: str,
        resolved: ResolvedWorkspaceDatasource,
        user_name: str,
    ) -> CatalogContext:
        ds_type = (resolved.datasource_type or "").strip().lower()
        if not ds_type:
            raise ForgeError("Datasource type is missing", status_code=500)

        secret_resolver = SecretResolver()
        config = dict(resolved.config_json or {})

        if ds_type == "databricks":
            config = secret_resolver.inject_if_missing(config, secret_ref=resolved.secret_ref, key="token")
            workspace_url = str(
                config.get("host")
                or config.get("workspace_url")
                or config.get("server")
                or ""
            ).strip()
            if not workspace_url:
                raise ForgeError(
                    f"Workspace '{workspace_id}' datasource is missing Databricks host",
                    status_code=500,
                )

            warehouse_id = str(
                config.get("warehouse_id")
                or config.get("default_warehouse_id")
                or self._warehouse_from_http_path(config.get("http_path"))
                or ""
            ).strip()
            if not warehouse_id:
                warehouse_id = self._resolve_default_warehouse_id(workspace_id)

            token = str(config.get("token") or "").strip()
            token_provider = (
                _StaticTokenProvider(token)
                if token
                else DatabricksWorkspaceForgeTokenPort(workspace_host=workspace_url, workspace_id=workspace_id)
            )

            sql_exec: ForgeQueryPort = DatabricksForgeQueryPort(
                base_url=workspace_url.rstrip("/"),
                token_provider=token_provider,
                default_warehouse_id=warehouse_id,
                default_catalog=str(config.get("catalog") or resolved.default_catalog or "").strip() or None,
                default_schema=str(config.get("schema") or resolved.default_schema or "").strip() or None,
            )
            return CatalogContext(
                workspace_id=workspace_id,
                workspace_url=workspace_url.rstrip("/"),
                warehouse_id=warehouse_id,
                user_name=user_name,
                sql_exec=sql_exec,
            )

        # Non-Databricks sources use the analytics executor stack and a ForgeQueryPort adapter.
        if ds_type in {"snowflake", "mysql", "postgres", "bigquery"}:
            config = secret_resolver.inject_if_missing(config, secret_ref=resolved.secret_ref, key="password")
            config.setdefault("type", ds_type)
            if ds_type == "postgres":
                # Placeholder compatibility until a dedicated Postgres executor exists.
                raise ForgeError("Postgres datasource executor is not configured yet", status_code=400)
            if ds_type == "bigquery":
                raise ForgeError("BigQuery datasource executor is not configured yet", status_code=400)
            analytics_executor = ExecutorFactory.create(ds_type, config)
            sql_exec = AnalyticsExecutorForgeAdapter(analytics_executor)
            return CatalogContext(
                workspace_id=workspace_id,
                workspace_url="",
                warehouse_id="",
                user_name=user_name,
                sql_exec=sql_exec,
            )

        raise ForgeError(f"Unsupported datasource type '{ds_type}'", status_code=400)

    @staticmethod
    def _warehouse_from_http_path(http_path: object) -> Optional[str]:
        path = str(http_path or "").strip()
        if not path:
            return None
        token = path.split("/")[-1].strip()
        return token or None

    def _assert_request_workspace_access(self, workspace_id: str) -> None:
        if not has_request_context():
            return

        user_id = str(getattr(g, "user_id", "") or "").strip()
        if not user_id:
            return

        WorkspaceAccessService().assert_workspace_access(user_id=user_id, workspace_id=workspace_id)

    def _resolve_workspace_url(self, workspace_id: str) -> str:
        ws = WorkspaceService().get_workspace(workspace_id=workspace_id)

        if isinstance(ws, dict):
            url = ws.get("server") or ws.get("host_url") or ws.get("workspace_url")
        else:
            url = (
                getattr(ws, "server", None)
                or getattr(ws, "host_url", None)
                or getattr(ws, "workspace_url", None)
            )

        if not url:
            raise ForgeError(
                f"Workspace '{workspace_id}' did not resolve to a server URL",
                status_code=400,
            )

        return str(url).rstrip("/")

    def _resolve_default_warehouse_id(self, workspace_id: str) -> str:
        workspace_url = self._resolve_workspace_url(workspace_id)
        token_manager = DatabricksWorkspaceForgeTokenPort(
            workspace_host=workspace_url,
            workspace_id=workspace_id,
        )
        wh = WarehouseService(token_manager=token_manager).get_warehouse_by_name(
            workspace_id=workspace_id,
            warehouse_name=DEFAULT_SQL_WAREHOUSE,
        )

        warehouse_id = wh.get("warehouse_id") if isinstance(wh, dict) else getattr(wh, "warehouse_id", None)

        if not warehouse_id:
            raise ForgeError(
                f"Default warehouse '{DEFAULT_SQL_WAREHOUSE}' not found for workspace '{workspace_id}'",
                status_code=400,
            )

        return str(warehouse_id)
