from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import urlparse

from app.exceptions.forge_error import ForgeError
from app.services.tenancy.datasource_resolver_service import WorkspaceDatasourceResolverService
from app.services.workspace_service import WorkspaceService

RESOLVER_WRAP_ERRORS = (OSError, RuntimeError, TypeError, ValueError)


class WorkspaceExternalLinkService:
    """Builds external console links for the datasource bound to a workspace."""

    def __init__(self) -> None:
        self._resolver = WorkspaceDatasourceResolverService()
        self._workspace_service = WorkspaceService()

    def list_links(self, *, workspace_id: str, allow_legacy_fallback: bool = True) -> Dict[str, Any]:
        ws = str(workspace_id or "").strip()
        if not ws:
            raise ForgeError("workspace_id is required", status_code=400)

        try:
            resolved = self._resolver.resolve_for_workspace(workspace_id=ws, require_active=True)
        except ForgeError:
            raise
        except RESOLVER_WRAP_ERRORS as exc:
            raise ForgeError("Failed to resolve workspace datasource", status_code=500, details={"workspace_id": ws, "error": str(exc)})

        if resolved is None:
            if allow_legacy_fallback:
                fallback = self._legacy_workspace_link(ws)
                if fallback is not None:
                    return {
                        "workspace_id": ws,
                        "datasource_type": "databricks",
                        "links": [fallback],
                    }
            return {"workspace_id": ws, "datasource_type": None, "links": []}

        cfg = dict(resolved.config_json or {})
        ds_type = str(resolved.datasource_type or "").strip().lower()
        url = self._resolve_external_url(ds_type=ds_type, config_json=cfg)
        if not url:
            return {
                "workspace_id": ws,
                "datasource_type": ds_type or None,
                "links": [],
            }

        label = self._provider_label(ds_type)
        return {
            "workspace_id": ws,
            "datasource_type": ds_type or None,
            "links": [
                {
                    "key": f"{ds_type}_console",
                    "label": label,
                    "url": url,
                    "provider": ds_type or "unknown",
                    "is_default": True,
                }
            ],
        }

    def _legacy_workspace_link(self, workspace_id: str) -> Optional[Dict[str, Any]]:
        ws = self._workspace_service.get_workspace(workspace_id)
        raw = ""
        if isinstance(ws, dict):
            raw = str(ws.get("server") or ws.get("workspace_url") or ws.get("host_url") or "").strip()
        if not raw:
            return None
        url = _normalize_url(raw)
        if not url:
            return None
        return {
            "key": "databricks_console",
            "label": "Databricks",
            "url": url,
            "provider": "databricks",
            "is_default": True,
        }

    @staticmethod
    def _provider_label(ds_type: str) -> str:
        labels = {
            "databricks": "Databricks",
            "snowflake": "Snowflake",
            "mysql": "MySQL",
            "postgres": "PostgreSQL",
            "bigquery": "BigQuery",
        }
        return labels.get(ds_type, "Datasource")

    def _resolve_external_url(self, *, ds_type: str, config_json: Dict[str, Any]) -> Optional[str]:
        explicit = (
            config_json.get("external_url")
            or config_json.get("console_url")
            or config_json.get("web_url")
        )
        if explicit:
            return _normalize_url(str(explicit))

        if ds_type == "databricks":
            host = config_json.get("host") or config_json.get("workspace_url") or config_json.get("server")
            return _normalize_url(str(host or ""))

        if ds_type == "snowflake":
            host = config_json.get("host") or config_json.get("account_url")
            if host:
                return _normalize_url(str(host))
            account = str(config_json.get("account") or "").strip()
            if not account:
                return None
            if account.startswith(("http://", "https://")):
                return _normalize_url(account)
            if "." in account:
                return _normalize_url(f"https://{account}")
            return _normalize_url(f"https://{account}.snowflakecomputing.com")

        # MySQL/Postgres/BigQuery usually don't have a single stable browser console
        # unless integrators provide external_url/console_url explicitly.
        return None


def _normalize_url(raw: str) -> Optional[str]:
    value = str(raw or "").strip()
    if not value:
        return None
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return None
    return value.rstrip("/")
