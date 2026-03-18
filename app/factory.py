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

from app.adapters.databricks_token_manager import DatabricksForgeTokenPort
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
from app.routes import planner_domain as _planner_domain  # noqa: F401
from app.routes import planner_llm as _planner_llm  # noqa: F401
from app.routes.admin_routes import admin_ns
from app.routes.ai import ai_ns
from app.routes.auth_routes import qf_auth_ns
from app.routes.chat_minimal import chat_ns
from app.routes.data_environment import data_environment_ns
from app.routes.datasource_routes import datasource_ns
from app.routes.ingestion_routes import ingestion_ns
from app.routes.domain_routes import qf_domains_ns
from app.routes.domain_profile_embeddings import domain_profile_embeddings_ns
from app.routes.embeddings import embeddings_ns
from app.routes.execution_routes import executions_ns
from app.routes.export_routes import exports_ns
from app.routes.forge_insights import forge_insights_ns
from app.routes.destination_routes import destinations_ns
from app.routes.forge_match_routes import forge_match_ns
from app.routes.query_analysis_routes import query_analysis_ns
from app.routes.skills_routes import skills_ns
from app.routes.nlp_review import nlp_review_ns
from app.routes.nlp_routes import nlp_ns
from app.routes.nlp_tier2 import nlp_tier2_ns
from app.routes.otp_routes import otp_ns
from app.routes.planner_extract import planner_ns
from app.routes.product_groups_routes import product_group_ns
from app.routes.product_routes import product_ns
from app.routes.prompt_feedback import prompt_feedback_ns
from app.routes.public_sales_inquiry import public_ns
from app.routes.query_forge_routes import query_forge_ns
from app.routes.query_studio_routes import query_studio_ns
from app.routes.query_tree_routes import qf_saved_query_ns, qf_tree_ns
from app.routes.role_routes import role_ns
from app.routes.semantic_concepts import (
    semantic_concept_aliases_ns,
    semantic_concept_column_maps_ns,
    semantic_concepts_ns,
    semantic_value_aliases_ns,
)
from app.routes.semantic_mappings import semantic_mappings_ns
from app.routes.semantic_registry import semantic_registry_ns
from app.routes.semantic_relationships import semantic_relationships_ns
from app.routes.semantic_routes import semantic_ns
from app.routes.semantic_suggestions import semantic_suggestions_ns
from app.routes.user_routes import qf_user_ns
from app.routes.user_workspace_routes import user_workspace_ns
from app.routes.value_override_routes import value_override_ns
from app.routes.vector_domains import vector_ns
from app.routes.version_routes import version_ns
from app.routes.workspace_inventory_routes import wsinv_ns
from app.routes.workspace_llm_routes import llm_providers_ns, llm_roles_ns, workspace_llm_ns
from app.routes.workspace_routes import workspace_ns
from app.routes.workspace_table_routes import workspace_tables_ns
from app.routes.dictionary_routes import dictionary_ns
from app.services.analytics.config_loader import load_analytics_config
from app.services.analytics.executor_factory import ExecutorFactory
from app.services.analytics.registry import AnalyticsDatasourceRegistry
from app.services.auth_service import AuthService
from app.services.base_service import build_url
from app.services.semantic.concept_seed import ConceptSeedService
from app.services.tenancy.datasource_catalog_service import DatasourceCatalogService
from app.services.tenancy.secret_resolver import SecretResolver

NAME = "api"
VERSION = "v1"

auth_service = AuthService()


def _is_placeholder(value: str) -> bool:
    return "${" in value and "}" in value


def _is_configured_value(value: str) -> bool:
    raw = (value or "").strip()
    return bool(raw and not _is_placeholder(raw))


def _needs_databricks_token_manager(analytics_config: dict[str, dict[str, Any]]) -> bool:
    """Return True when a configured Databricks datasource lacks a usable static token."""
    for cfg in analytics_config.values():
        ds_type = str((cfg or {}).get("type") or "").strip().lower()
        if ds_type != "databricks":
            continue
        host_raw = str((cfg or {}).get("host") or "").strip()
        http_path_raw = str((cfg or {}).get("http_path") or "").strip()
        if not (_is_configured_value(host_raw) and _is_configured_value(http_path_raw)):
            continue
        token_raw = str((cfg or {}).get("token") or "").strip()
        if (not token_raw) or _is_placeholder(token_raw):
            return True
    return False


def _databricks_oauth_configured() -> bool:
    token_url = (os.getenv("DATABRICKS_TOKEN_URL") or "").strip()
    client_id = (os.getenv("DATABRICKS_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("DATABRICKS_CLIENT_SECRET") or "").strip()
    return bool(token_url.startswith(("http://", "https://")) and client_id and client_secret)



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

    api.add_namespace(qf_auth_ns, path=build_url("/", NAME, VERSION, "auth"))
    api.add_namespace(qf_user_ns, path=build_url("/", NAME, VERSION, "users"))
    api.add_namespace(workspace_ns, path=build_url("/", NAME, VERSION, "workspaces"))
    api.add_namespace(workspace_tables_ns, path=build_url("/", NAME, VERSION, "workspace-tables"))
    api.add_namespace(dictionary_ns, path=build_url("/", NAME, VERSION, "dictionary"))
    api.add_namespace(user_workspace_ns, path=build_url("/", NAME, VERSION, "user-workspaces"))
    api.add_namespace(role_ns, path=build_url("/", NAME, VERSION, "roles"))
    api.add_namespace(admin_ns, path=build_url("/", NAME, VERSION, "admin"))
    api.add_namespace(product_ns, path=build_url("/", NAME, VERSION, "products"))
    api.add_namespace(planner_ns, path=build_url("/", NAME, VERSION, "planner"))
    api.add_namespace(otp_ns, path=build_url("/", NAME, VERSION, "otp"))
    api.add_namespace(product_group_ns, path=build_url("/", NAME, VERSION, "product-groups"))
    api.add_namespace(value_override_ns, path=build_url("/", NAME, VERSION, "value_overrides"))
    api.add_namespace(version_ns, path=build_url("/", NAME, VERSION, "version"))
    api.add_namespace(public_ns, path=build_url("/", NAME, VERSION, "public"))
    api.add_namespace(qf_domains_ns, path=build_url("/", NAME, VERSION, "domains"))
    api.add_namespace(domain_profile_embeddings_ns, path=build_url("/", NAME, VERSION, "domain-profiles"))
    api.add_namespace(embeddings_ns, path=build_url("/", NAME, VERSION, "embeddings"))
    api.add_namespace(executions_ns, path=build_url("/", NAME, VERSION, "executions"))
    api.add_namespace(exports_ns, path=build_url("/", NAME, VERSION, "exports"))
    api.add_namespace(wsinv_ns, path=build_url("/", NAME, VERSION, "workspace-inventory"))
    api.add_namespace(nlp_ns, path=build_url("/", NAME, VERSION, "nlp"))
    api.add_namespace(nlp_tier2_ns, path=build_url("/", NAME, VERSION, "nlp"))
    api.add_namespace(nlp_review_ns, path=build_url("/", NAME, VERSION, "nlp"))
    api.add_namespace(query_forge_ns, path=build_url("/", NAME, VERSION, "query"))
    api.add_namespace(query_studio_ns, path=build_url("/", NAME, VERSION, "query-studio"))
    api.add_namespace(qf_tree_ns, path=build_url("/", NAME, VERSION, "query-tree"))
    api.add_namespace(qf_saved_query_ns, path=build_url("/", NAME, VERSION, "saved-queries"))
    api.add_namespace(ai_ns, path=build_url("/", NAME, VERSION, "ai"))
    api.add_namespace(prompt_feedback_ns, path=build_url("/", NAME, VERSION, "prompt-feedback"))
    api.add_namespace(forge_insights_ns, path=build_url("/", NAME, VERSION, "forge-insights"))
    api.add_namespace(destinations_ns, path=build_url("/", NAME, VERSION, "workspaces") + "/<workspace_id>/destinations")
    api.add_namespace(forge_match_ns, path=build_url("/", NAME, VERSION, "forge-match"))
    api.add_namespace(query_analysis_ns, path=build_url("/", NAME, VERSION, "queries"))
    api.add_namespace(skills_ns, path=build_url("/", NAME, VERSION, "skills"))
    api.add_namespace(chat_ns, path=build_url("/", NAME, VERSION, "chat"))
    api.add_namespace(semantic_concepts_ns, path=build_url("/", NAME, VERSION, "semantic", "concepts"))
    api.add_namespace(semantic_concept_aliases_ns, path=build_url("/", NAME, VERSION, "semantic", "concept-aliases"))
    api.add_namespace(semantic_value_aliases_ns, path=build_url("/", NAME, VERSION, "semantic", "value-aliases"))
    api.add_namespace(semantic_concept_column_maps_ns, path=build_url("/", NAME, VERSION, "semantic", "concept-column-maps"))
    api.add_namespace(semantic_registry_ns, path=build_url("/", NAME, VERSION, "semantic", "registry"))
    api.add_namespace(semantic_mappings_ns, path=build_url("/", NAME, VERSION, "semantic", "mappings"))
    api.add_namespace(semantic_relationships_ns, path=build_url("/", NAME, VERSION, "semantic", "relationships"))
    api.add_namespace(semantic_suggestions_ns, path=build_url("/", NAME, VERSION, "semantic", "suggestions"))
    api.add_namespace(semantic_ns, path=build_url("/", NAME, VERSION, "semantic"))
    api.add_namespace(vector_ns, path=build_url("/", NAME, VERSION, "vector"))
    api.add_namespace(data_environment_ns, path=f"/{NAME}/{VERSION}/data-environment")
    api.add_namespace(datasource_ns, path=build_url("/", NAME, VERSION, "datasources"))
    api.add_namespace(ingestion_ns, path=build_url("/", NAME, VERSION, "ingestion"))
    api.add_namespace(llm_roles_ns, path=build_url("/", NAME, VERSION, "llm-roles"))
    api.add_namespace(llm_providers_ns, path=build_url("/", NAME, VERSION, "llm-providers"))
    api.add_namespace(workspace_llm_ns, path=build_url("/", NAME, VERSION))

    configure_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting the application...")

    if SEMANTIC_CONCEPT_SEED_ON_STARTUP:
        try:
            ConceptSeedService().ensure_seeded(SEMANTIC_VERTICAL_DEFAULT)
            logger.info("Seeded semantic concepts on startup for vertical=%s", SEMANTIC_VERTICAL_DEFAULT)
        except Exception:
            logger.exception("Semantic concept startup seed failed")

    bootstrap_analytics_config: dict[str, dict[str, Any]] | None = None
    try:
        bootstrap_analytics_config = load_analytics_config()
    except Exception:
        logger.exception("Failed to load analytics config for token-manager bootstrap")

    if bootstrap_analytics_config is None:
        logger.warning("Databricks token manager bootstrap skipped: analytics config could not be loaded")
    elif _needs_databricks_token_manager(bootstrap_analytics_config):
        if _databricks_oauth_configured():
            databricks_token_manager = DatabricksForgeTokenPort()
            databricks_token_manager.start_auto_refresh()
            app.config["DATABRICKS_TOKEN_MANAGER"] = databricks_token_manager
        else:
            logger.warning(
                "Databricks token manager not started: OAuth env is incomplete for configured Databricks datasource(s)"
            )
    else:
        logger.info("Databricks token manager not started: no Databricks datasource needs token refresh")


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

    _register_analytics_registry(app, config=bootstrap_analytics_config)

    return app
