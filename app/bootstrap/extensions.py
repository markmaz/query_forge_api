from __future__ import annotations

import logging

from flask import Flask
from flask_cors import CORS
from flask_restx import Api

from app.celery_app import celery, configure_forge_celery
from app.config import (
    AWS_ACCESS_KEY_ID,
    AWS_REGION,
    AWS_SECRET_ACCESS_KEY,
    AWS_SESSION_TOKEN,
    DESTINATION_ENCRYPTION_KEY,
    FRONTEND_ALLOWED_ORIGINS,
    FRONTEND_BASE_URL,
    LLM_INSTANCE_ID,
    LLM_STATUS_CACHE_SECONDS,
    QF_FORGE_INSIGHTS_ENABLED,
    QF_MINIMAL_CHAT_ENABLED,
    SEMANTIC_CONCEPT_SEED_ON_STARTUP,
    SEMANTIC_VERTICAL_DEFAULT,
    VALKEY_CONFIG,
    VLLM_BASE_URL,
    VLLM_MODEL,
    VLLM_TIMEOUT,
)
from app.config.logging_config import configure_logging
from app.config.mail_config import ForgeMailConfig
from app.extensions import mail
from app.features import register_features
from app.services.analytics.registry import AnalyticsDatasourceRegistry
from app.services.semantic.concept_seed import ConceptSeedService


def apply_runtime_config(app: Flask) -> None:
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
    app.config["FRONTEND_ALLOWED_ORIGINS"] = list(FRONTEND_ALLOWED_ORIGINS)
    app.config["DESTINATION_ENCRYPTION_KEY"] = DESTINATION_ENCRYPTION_KEY
    if not app.config["LLM_INSTANCE_ID"]:
        raise RuntimeError("LLM_INSTANCE_ID environment variable is required")
    if not app.config["AWS_ACCESS_KEY_ID"] or not app.config["AWS_SECRET_ACCESS_KEY"]:
        raise RuntimeError(
            "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables are required"
        )


def init_framework_extensions(app: Flask) -> Api:
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
        resources={r"/*": {"origins": list(FRONTEND_ALLOWED_ORIGINS)}},
        supports_credentials=True,
        expose_headers=["Content-Disposition"],
    )
    register_features(api)
    return api


def initialize_domain_extensions(app: Flask) -> None:
    app.extensions["analytics_registry"] = AnalyticsDatasourceRegistry({})


def initialize_startup_tasks() -> None:
    configure_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting the application...")
    if SEMANTIC_CONCEPT_SEED_ON_STARTUP:
        try:
            ConceptSeedService().ensure_seeded(SEMANTIC_VERTICAL_DEFAULT)
            logger.info("Seeded semantic concepts on startup for vertical=%s", SEMANTIC_VERTICAL_DEFAULT)
        except Exception:
            logger.exception("Semantic concept startup seed failed")


def register_cli_commands(app: Flask) -> None:
    from app.commands.create_superuser import create_superuser_command
    from app.commands.encrypt_datasource_secrets import encrypt_datasource_secrets_command
    from app.commands.seed_rbac_roles import seed_rbac_roles_command

    app.cli.add_command(create_superuser_command)
    app.cli.add_command(encrypt_datasource_secrets_command)
    app.cli.add_command(seed_rbac_roles_command)
