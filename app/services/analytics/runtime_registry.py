from __future__ import annotations

import logging
from typing import Optional

from app.ports.sql_executor import ForgeQueryPort
from app.services.analytics.executor_factory import ExecutorFactory
from app.services.analytics.registry import AnalyticsDatasourceRegistry
from app.services.tenancy.datasource_catalog_service import DatasourceCatalogService
from app.services.tenancy.secret_resolver import SecretResolver

logger = logging.getLogger(__name__)


def build_runtime_registry(
    *,
    sql: Optional[ForgeQueryPort] = None,
    fallback_registry: AnalyticsDatasourceRegistry | None = None,
) -> AnalyticsDatasourceRegistry:
    catalog = DatasourceCatalogService(sql=sql)
    configs = catalog.load_all_executor_configs()
    secrets = SecretResolver()
    executors = {}

    for name, raw_config in configs.items():
        cfg = dict(raw_config or {})
        ds_type = str(cfg.get("type") or "").strip().lower()
        try:
            cfg = _inject_runtime_secret(cfg, ds_type=ds_type, secrets=secrets)
            executors[name] = ExecutorFactory.create(ds_type, cfg)
        except Exception:
            logger.exception("Skipping datasource '%s' while building runtime analytics registry", name)

    if executors:
        return AnalyticsDatasourceRegistry(executors)
    if fallback_registry is not None:
        return fallback_registry
    return AnalyticsDatasourceRegistry({})


def _inject_runtime_secret(
    config: dict,
    *,
    ds_type: str,
    secrets: SecretResolver,
) -> dict:
    cfg = dict(config or {})
    secret_ref = cfg.get("_secret_ref")

    if ds_type == "databricks":
        auth_method = str(cfg.get("auth_method") or "").strip().lower()
        if auth_method != "oauth_client_credentials":
            return secrets.inject_if_missing(cfg, secret_ref=secret_ref, key="token")
        return cfg

    if ds_type in {"snowflake", "mysql"}:
        return secrets.inject_if_missing(cfg, secret_ref=secret_ref, key="password")

    return cfg
