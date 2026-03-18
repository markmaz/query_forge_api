from __future__ import annotations

import logging
from typing import Optional, Tuple

from flask import current_app
from flask_restx import Namespace
from app.routes.forge_resource import ForgeResource

from app.decorators.security import token_required
from app.decorators.rbac import require_role
from app.exceptions.forge_error import ForgeError
from app.services.llm_environment_service import LLMEnvironmentService

logger = logging.getLogger(__name__)

data_environment_ns = Namespace("data-environment", description="LLM environment controls")

_service_cache: Optional[LLMEnvironmentService] = None
_service_cache_key: Optional[Tuple[str, str, int, str, str, str]] = None


def _get_service() -> LLMEnvironmentService:
    global _service_cache, _service_cache_key

    region = str(current_app.config.get("AWS_REGION") or "").strip() or "us-east-1"
    instance_id = str(current_app.config.get("LLM_INSTANCE_ID") or "").strip()
    cache_seconds = int(current_app.config.get("LLM_STATUS_CACHE_SECONDS") or 5)
    aws_access_key_id = str(current_app.config.get("AWS_ACCESS_KEY_ID") or "").strip()
    aws_secret_access_key = str(current_app.config.get("AWS_SECRET_ACCESS_KEY") or "").strip()
    aws_session_token = str(current_app.config.get("AWS_SESSION_TOKEN") or "").strip()

    cache_key = (
        region,
        instance_id,
        cache_seconds,
        aws_access_key_id,
        aws_secret_access_key,
        aws_session_token,
    )
    if _service_cache is None or _service_cache_key != cache_key:
        _service_cache = LLMEnvironmentService(
            region=region,
            instance_id=instance_id,
            cache_seconds=cache_seconds,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token or None,
        )
        _service_cache_key = cache_key
    return _service_cache


def _handle_service_error(e: ForgeError):
    return {"error": str(e), "details": e.details}, e.status_code


@data_environment_ns.route("/llm/start")
class LLMStart(ForgeResource):
    @token_required
    @require_role("system:admin")
    def post(self):
        logger.info("API request: start LLM environment")
        try:
            return _get_service().start_instance(), 200
        except ForgeError as e:
            return _handle_service_error(e)


@data_environment_ns.route("/llm/stop")
class LLMStop(ForgeResource):
    @token_required
    @require_role("system:admin")
    def post(self):
        logger.info("API request: stop LLM environment")
        try:
            return _get_service().stop_instance(), 200
        except ForgeError as e:
            return _handle_service_error(e)


@data_environment_ns.route("/llm/status")
class LLMStatus(ForgeResource):
    @token_required
    @require_role("system:admin")
    def get(self):
        try:
            return _get_service().get_instance_status(), 200
        except ForgeError as e:
            return _handle_service_error(e)
