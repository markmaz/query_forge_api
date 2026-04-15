from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import SQLAlchemyError

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.services.tenancy.datasource_config_crypto import decrypt_datasource_config


class DatasourceCatalogService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def list_datasources(self, *, include_inactive: bool = False) -> List[Dict[str, Any]]:
        try:
            rows = self._sql.execute_query_mappings(
                """
                SELECT
                  d.id,
                  d.organization_id,
                  d.name,
                  d.slug,
                  d.type,
                  COALESCE(d.is_active, 1) AS is_active,
                  d.last_tested_at,
                  d.last_test_status,
                  d.last_test_message,
                  d.created_at,
                  d.updated_at
                FROM datasource d
                WHERE (:include_inactive = 1 OR COALESCE(d.is_active, 1) = 1)
                ORDER BY d.organization_id, d.name
                """,
                {"include_inactive": 1 if include_inactive else 0},
            )
        except SQLAlchemyError:
            return []

        out: List[Dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "id": row.get("id"),
                    "organization_id": row.get("organization_id"),
                    "name": row.get("name"),
                    "slug": row.get("slug"),
                    "type": row.get("type"),
                    "is_active": bool(int(row.get("is_active") or 0)),
                    "last_tested_at": row.get("last_tested_at"),
                    "last_test_status": row.get("last_test_status"),
                    "last_test_message": row.get("last_test_message"),
                    "created_at": row.get("created_at"),
                    "updated_at": row.get("updated_at"),
                }
            )
        return out

    def load_executor_config_by_name(self, *, name: str) -> Optional[Dict[str, Any]]:
        ds_name = str(name or "").strip()
        if not ds_name:
            return None
        try:
            rows = self._sql.execute_query_mappings(
                """
                SELECT id, organization_id, name, slug, type, secret_ref, config_json, COALESCE(is_active, 1) AS is_active
                FROM datasource
                WHERE (name = :name OR slug = :name)
                LIMIT 1
                """,
                {"name": ds_name},
            )
        except SQLAlchemyError:
            return None
        if not rows:
            return None

        row = dict(rows[0])
        cfg = self._coerce_json_obj(row.get("config_json"))
        datasource_type = str(row.get("type") or "").strip().lower()
        cfg = decrypt_datasource_config(datasource_type, cfg)
        cfg.setdefault("type", datasource_type)
        cfg["_datasource_id"] = row.get("id")
        cfg["_organization_id"] = row.get("organization_id")
        cfg["_secret_ref"] = row.get("secret_ref")
        cfg["_is_active"] = bool(int(row.get("is_active") or 0))
        cfg["_name"] = row.get("name")
        cfg["_slug"] = row.get("slug")
        return cfg

    def load_all_executor_configs(self) -> Dict[str, Dict[str, Any]]:
        try:
            rows = self._sql.execute_query_mappings(
                """
                SELECT id, organization_id, name, slug, type, secret_ref, config_json, COALESCE(is_active, 1) AS is_active
                FROM datasource
                WHERE COALESCE(is_active, 1) = 1
                """
            )
        except SQLAlchemyError:
            return {}

        out: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            cfg = self._coerce_json_obj(row.get("config_json"))
            datasource_type = str(row.get("type") or "").strip().lower()
            cfg = decrypt_datasource_config(datasource_type, cfg)
            cfg.setdefault("type", datasource_type)
            cfg["_datasource_id"] = row.get("id")
            cfg["_organization_id"] = row.get("organization_id")
            cfg["_secret_ref"] = row.get("secret_ref")
            cfg["_is_active"] = bool(int(row.get("is_active") or 0))
            cfg["_name"] = row.get("name")
            cfg["_slug"] = row.get("slug")

            name = str(row.get("name") or "").strip()
            slug = str(row.get("slug") or "").strip()
            if name and name not in out:
                out[name] = dict(cfg)
            if slug:
                out[slug] = dict(cfg)
        return out

    @staticmethod
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
                if isinstance(parsed, dict):
                    return parsed
            except (TypeError, ValueError, json.JSONDecodeError):
                return {}
        return {}
