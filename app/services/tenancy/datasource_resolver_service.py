from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.tenancy.datasource_config_crypto import decrypt_datasource_config


@dataclass(frozen=True)
class ResolvedWorkspaceDatasource:
    workspace_id: str
    workspace_name: Optional[str]
    organization_id: Optional[str]
    organization_is_active: bool
    workspace_is_active: bool
    datasource_id: int
    datasource_name: str
    datasource_slug: str
    datasource_type: str
    datasource_is_active: bool
    config_json: Dict[str, Any]
    secret_ref: Optional[str]
    default_catalog: Optional[str]
    default_schema: Optional[str]


class WorkspaceDatasourceResolverService:
    """Resolves datasource metadata for a workspace.

    Workspace remains the primary routing key; datasource is resolved server-side.
    """

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def resolve_for_workspace(self, *, workspace_id: str, require_active: bool = True) -> Optional[ResolvedWorkspaceDatasource]:
        ws = str(workspace_id or "").strip()
        if not ws:
            raise ForgeError("workspace_id is required", status_code=400)

        rows = self._sql.execute_query_mappings(
            """
            SELECT
              w.id AS workspace_id,
              w.name AS workspace_name,
              w.organization_id AS workspace_organization_id,
              COALESCE(o.is_active, 1) AS organization_is_active,
              COALESCE(w.is_active, 1) AS workspace_is_active,
              w.datasource_id,
              w.default_catalog,
              w.default_schema,
              d.id AS datasource_id,
              d.organization_id AS datasource_organization_id,
              d.name AS datasource_name,
              d.slug AS datasource_slug,
              d.type AS datasource_type,
              COALESCE(d.is_active, 1) AS datasource_is_active,
              d.config_json,
              d.secret_ref
            FROM workspace w
            LEFT JOIN organization o
              ON o.id = w.organization_id
            LEFT JOIN datasource d
              ON d.id = w.datasource_id
            WHERE w.id = :ws
            LIMIT 1
            """,
            {"ws": ws},
        )
        if not rows:
            raise ForgeError("Workspace not found", status_code=404)

        row = dict(rows[0])
        org_active_raw = row.get("organization_is_active")
        organization_active = True if org_active_raw is None else bool(int(org_active_raw or 0))
        workspace_active = bool(int(row.get("workspace_is_active") or 0))
        if require_active and row.get("workspace_organization_id") is not None and not organization_active:
            raise ForgeError("Organization is inactive", status_code=403)
        if require_active and not workspace_active:
            raise ForgeError("Workspace is inactive", status_code=403)

        datasource_id = row.get("datasource_id")
        if datasource_id is None:
            return None

        datasource_active = bool(int(row.get("datasource_is_active") or 0))
        if require_active and not datasource_active:
            raise ForgeError("Datasource is inactive", status_code=403)

        ws_org = row.get("workspace_organization_id")
        ds_org = row.get("datasource_organization_id")
        if ws_org and ds_org and str(ws_org) != str(ds_org):
            raise ForgeError("Workspace/datasource organization mismatch", status_code=500)

        datasource_type = str(row.get("datasource_type") or "").strip().lower()
        config_json = decrypt_datasource_config(
            datasource_type,
            self._coerce_json_obj(row.get("config_json")),
        )

        return ResolvedWorkspaceDatasource(
            workspace_id=str(row.get("workspace_id") or ws),
            workspace_name=(str(row.get("workspace_name")) if row.get("workspace_name") is not None else None),
            organization_id=(str(ws_org) if ws_org is not None else None),
            organization_is_active=organization_active,
            workspace_is_active=workspace_active,
            datasource_id=int(datasource_id),
            datasource_name=str(row.get("datasource_name") or f"datasource-{datasource_id}"),
            datasource_slug=str(row.get("datasource_slug") or ""),
            datasource_type=datasource_type,
            datasource_is_active=datasource_active,
            config_json=config_json,
            secret_ref=(str(row.get("secret_ref")) if row.get("secret_ref") is not None else None),
            default_catalog=(str(row.get("default_catalog")) if row.get("default_catalog") is not None else None),
            default_schema=(str(row.get("default_schema")) if row.get("default_schema") is not None else None),
        )

    @staticmethod
    def _coerce_json_obj(value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8", errors="ignore")
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return {}
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
                return {}
            except Exception:
                return {}
        return {}
