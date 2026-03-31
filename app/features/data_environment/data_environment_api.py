from __future__ import annotations

import logging

from flask_restx import Namespace, Resource

from app.decorators.rbac import require_role
from app.decorators.security import token_required
from app.features.data_environment.service import data_environment_feature_service

logger = logging.getLogger(__name__)

data_environment_ns = Namespace("data-environment", description="LLM environment controls")


@data_environment_ns.route("/llm/start")
class LLMStart(Resource):
    @token_required
    @require_role("system:admin")
    def post(self):
        logger.info("API request: start LLM environment")
        try:
            return data_environment_feature_service.get_service().start_instance(), 200
        except Exception as error:
            from app.exceptions.forge_error import ForgeError

            if isinstance(error, ForgeError):
                return data_environment_feature_service.handle_service_error(error)
            raise


@data_environment_ns.route("/llm/stop")
class LLMStop(Resource):
    @token_required
    @require_role("system:admin")
    def post(self):
        logger.info("API request: stop LLM environment")
        try:
            return data_environment_feature_service.get_service().stop_instance(), 200
        except Exception as error:
            from app.exceptions.forge_error import ForgeError

            if isinstance(error, ForgeError):
                return data_environment_feature_service.handle_service_error(error)
            raise


@data_environment_ns.route("/llm/status")
class LLMStatus(Resource):
    @token_required
    @require_role("system:admin")
    def get(self):
        try:
            return data_environment_feature_service.get_service().get_instance_status(), 200
        except Exception as error:
            from app.exceptions.forge_error import ForgeError

            if isinstance(error, ForgeError):
                return data_environment_feature_service.handle_service_error(error)
            raise
