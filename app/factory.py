from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any

import valkey
from flask import Flask, g, jsonify, request
from flask_cors import CORS
from flask_restx import Api

from app.celery_app import celery, configure_forge_celery
from app.config import (
    AWS_ACCESS_KEY_ID,
    AWS_REGION,
    AWS_SECRET_ACCESS_KEY,
    AWS_SESSION_TOKEN,
    FRONTEND_BASE_URL,
    LLM_INSTANCE_ID,
    LLM_STATUS_CACHE_SECONDS,
    LOG_QUEUE,
    QF_FORGE_INSIGHTS_ENABLED,
    QF_MINIMAL_CHAT_ENABLED,
    SEMANTIC_CONCEPT_SEED_ON_STARTUP,
    SEMANTIC_VERTICAL_DEFAULT,
    VALKEY_ADDRESS,
    VALKEY_CONFIG,
    VALKEY_PORT,
    VLLM_BASE_URL,
    VLLM_MODEL,
    VLLM_TIMEOUT,
)
from app.config.logging_config import configure_logging
from app.config.mail_config import ForgeMailConfig
from app.exceptions.forge_error import ForgeError
from app.extensions import mail
from app.api_config import NAME, VERSION, build_url
from app.features import register_features
from app.services.analytics.config_loader import load_analytics_config
from app.services.analytics.executor_factory import ExecutorFactory
from app.services.analytics.registry import AnalyticsDatasourceRegistry
from app.services.auth_service import AuthService
from app.services.semantic.concept_seed import ConceptSeedService
from app.services.tenancy.datasource_catalog_service import DatasourceCatalogService
from app.services.tenancy.secret_resolver import SecretResolver

auth_service = AuthService()


def _is_placeholder(value: str) -> bool:
    return "${" in value and "}" in value


def _is_configured_value(value: str) -> bool:
    raw = (value or "").strip()
    return bool(raw and not _is_placeholder(raw))





def _register_analytics_registry(
    app: Flask, *, config: dict[str, dict[str, Any]] | None = None
) -> None:  # noqa: F821
    """Load analytics datasource config and register the registry in ``app.extensions``.

    Failures are logged but never crash app startup — the registry will simply be
    absent or empty so that unrelated features are unaffected.
    """
    _logger = logging.getLogger(__name__)
    try:
        config = config if config is not None else load_analytics_config()
        config = dict(config or {})
        db_configs = DatasourceCatalogService().load_all_executor_configs()
        if db_configs:
            # DB-backed datasource definitions are the new source of truth.
            config.update(db_configs)
        executors = {}
        skipped: list[str] = []
        secret_resolver = SecretResolver()
        for name, cfg in config.items():
            try:
                effective_cfg = dict(cfg)
                ds_type = str(effective_cfg.get("type") or "").strip().lower()

                secret_ref = str(effective_cfg.get("_secret_ref") or "").strip()
                if secret_ref:
                    resolved_secret = secret_resolver.resolve(secret_ref)
                    if resolved_secret:
                        if ds_type == "databricks" and not effective_cfg.get("token"):
                            effective_cfg["token"] = resolved_secret
                        elif ds_type in {"snowflake", "mysql"} and not effective_cfg.get("password"):
                            effective_cfg["password"] = resolved_secret

                if str(effective_cfg.get("type") or "").strip().lower() == "databricks":
                    token_raw = str(effective_cfg.get("token") or "").strip()
                    if (not token_raw) or "${" in token_raw or "}" in token_raw:
                        token_manager = app.config.get("DATABRICKS_TOKEN_MANAGER")
                        if token_manager is not None:
                            effective_cfg.pop("token", None)
                            effective_cfg["token_provider"] = token_manager

                executors[name] = ExecutorFactory.create(effective_cfg["type"], effective_cfg)
            except Exception as exc:
                skipped.append(name)
                _logger.error(
                    "Skipping analytics datasource '%s' due to invalid configuration: %s",
                    name,
                    exc,
                )

        registry = AnalyticsDatasourceRegistry(executors)
        app.extensions["analytics_registry"] = registry
        if skipped:
            _logger.warning(
                "Analytics datasource registry initialised with %d datasource(s); skipped %d datasource(s): %s",
                len(executors),
                len(skipped),
                ", ".join(sorted(skipped)),
            )
        else:
            _logger.info(
                "Analytics datasource registry initialised with %d datasource(s): %s",
                len(executors),
                ", ".join(
                    f"{name}({executor.get_dialect()})" for name, executor in executors.items()
                ),
            )
    except Exception:
        _logger.exception("Failed to initialise analytics datasource registry")

def try_get_json_body(req):
    try:
        data = req.get_json()
        if data:
            masked = data.copy()
            for key in ["password", "token"]:
                if key in masked:
                    masked[key] = "*****"
            return masked
    except Exception:
        pass
    return None

def extract_user_id():
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        payload = auth_service.verify_token(token)
        if payload and isinstance(payload, dict):
            return payload.get("sub") or "unknown_user"
        return "unknown_user"
    return "unknown_user"

def create_app():
    app = Flask(__name__)
    app.config["RESTX_MASK_SWAGGER"] = False
    app.url_map.strict_slashes = False
    app.config["VLLM_BASE_URL"] = VLLM_BASE_URL
    app.config["VLLM_MODEL"] = VLLM_MODEL
    app.config["VLLM_TIMEOUT"] = VLLM_TIMEOUT
    app.config["AWS_REGION"] = AWS_REGION
    app.config["AWS_ACCESS_KEY_ID"] = AWS_ACCESS_KEY_ID
    app.config["AWS_SECRET_ACCESS_KEY"] = AWS_SECRET_ACCESS_KEY
    app.config["AWS_SESSION_TOKEN"] = AWS_SESSION_TOKEN
    app.config["LLM_INSTANCE_ID"] = LLM_INSTANCE_ID
    app.config["LLM_STATUS_CACHE_SECONDS"] = LLM_STATUS_CACHE_SECONDS
    app.config["QF_MINIMAL_CHAT_ENABLED"] = QF_MINIMAL_CHAT_ENABLED
    app.config["QF_FORGE_INSIGHTS_ENABLED"] = QF_FORGE_INSIGHTS_ENABLED
    app.config["FRONTEND_BASE_URL"] = FRONTEND_BASE_URL
    if not app.config["LLM_INSTANCE_ID"]:
        raise RuntimeError("LLM_INSTANCE_ID environment variable is required")
    if not app.config["AWS_ACCESS_KEY_ID"] or not app.config["AWS_SECRET_ACCESS_KEY"]:
        raise RuntimeError(
            "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables are required"
        )
    authorizations = {"BearerAuth": {"type": "apiKey", "in": "header", "name": "Authorization"}}

    app.config.from_object(ForgeMailConfig)
    mail.init_app(app=app)

    app.config["broker_url"] = VALKEY_CONFIG
    app.config["result_backend"] = VALKEY_CONFIG

    configure_forge_celery(app)
    app.config["CELERY"] = celery

    from app.skills.registry import SkillRegistry
    SkillRegistry.autodiscover("app.skills")

    api = Api(
        app,
        version="1.0",
        title="Query Forge API",
        description="The Query Forge REST API",
        doc="/swagger-ui",
        mask_swagger=False,
        security="BearerAuth",
        authorizations=authorizations,
    )

    CORS(
        app,
        resources={r"/*": {"origins": "*"}},
        supports_credentials=True,
        expose_headers=["Content-Disposition"],
    )

    register_features(api)

    configure_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting the application...")

    if SEMANTIC_CONCEPT_SEED_ON_STARTUP:
        try:
            ConceptSeedService().ensure_seeded(SEMANTIC_VERTICAL_DEFAULT)
            logger.info("Seeded semantic concepts on startup for vertical=%s", SEMANTIC_VERTICAL_DEFAULT)
        except Exception:
            logger.exception("Semantic concept startup seed failed")



    valkey_client = valkey.StrictValkey(host=VALKEY_ADDRESS, port=VALKEY_PORT, decode_responses=True)

    @app.before_request
    def log_request_metadata():
        g.start_time = time.time()
        g.correlation_id = str(uuid.uuid4())
        g.audit_data = {
            "timestamp": int(g.start_time),
            "correlation_id": g.correlation_id,
            "user_id": extract_user_id(),
            "endpoint": request.path,
            "method": request.method,
            "ip_address": request.headers.get("X-Forwarded-For", request.remote_addr),
            "user_agent": request.headers.get("User-Agent", "unknown"),
            "request_body": try_get_json_body(request),
            "authenticated": request.authorization is not None or hasattr(g, "user"),
        }

    @app.after_request
    def log_response_metadata(response):
        duration_ms = int((time.time() - g.start_time) * 1000)
        g.audit_data["status_code"] = response.status_code
        g.audit_data["response_time_ms"] = duration_ms
        try:
            valkey_client.rpush(LOG_QUEUE, json.dumps(g.audit_data))
        except Exception as e:
            app.logger.error(f"Error storing audit log in Valkey: {e}")

        response.headers["X-Correlation-ID"] = g.correlation_id
        return response

    @app.errorhandler(ForgeError)
    def handle_service_error(error):
        response = jsonify(error.to_dict())
        response.status_code = error.status_code
        return response

    bootstrap_analytics_config: dict[str, dict[str, Any]] | None = None
    try:
        bootstrap_analytics_config = load_analytics_config()
    except Exception:
        logger.exception("Failed to load analytics config")

    _register_analytics_registry(app, config=bootstrap_analytics_config)

    from app.commands.create_superuser import create_superuser_command
    app.cli.add_command(create_superuser_command)

    return app
