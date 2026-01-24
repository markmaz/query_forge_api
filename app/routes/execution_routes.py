from __future__ import annotations

import logging

from flask import request
from flask_restx import Namespace, Resource

from app.decorators.security import token_required
from app.exceptions.service_error import ServiceError
from app.routes._route_utils import get_workspace_id_from_header
from app.services.execution_service import ExecutionService

logger = logging.getLogger(__name__)
executions_ns = Namespace("executions", description="Databricks SQL executions")


def _handle_service_error(e: ServiceError):
    return {"error": str(e)}, getattr(e, "status_code", 400) or 400



def _service() -> ExecutionService:
    return ExecutionService()


@executions_ns.route("/start")
class ExecutionStart(Resource):
    """
    Example:
      curl -X POST /api/v1/executions/start \\
        -H "Authorization: Bearer <token>" \\
        -H "X-Workspace-Id: <workspace_id>" \\
        -H "Content-Type: application/json" \\
        -d '{"sql":"SELECT 1","params":{},"kind":"query_builder"}'
    """

    @token_required
    def post(self):
        try:
            workspace_id = get_workspace_id_from_header()
            payload = request.get_json(silent=True) or {}
            if not isinstance(payload, dict):
                raise ServiceError("Invalid JSON body", status_code=400)
            return _service().start(workspace_id, payload, dict(request.args))

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Execution start failed")
            return {"error": "Execution start failed"}, 500


@executions_ns.route("/<string:job_id>/status")
class ExecutionStatus(Resource):
    @token_required
    def get(self, job_id: str):
        try:
            workspace_id = get_workspace_id_from_header()
            return _service().status(workspace_id, job_id)

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Execution status failed")
            return {"error": "Execution status failed"}, 500


@executions_ns.route("/<string:job_id>/cancel")
class ExecutionCancel(Resource):
    """
    Example:
      curl -X POST /api/v1/executions/<job_id>/cancel \\
        -H "Authorization: Bearer <token>" \\
        -H "X-Workspace-Id: <workspace_id>"
    """

    @token_required
    def post(self, job_id: str):
        try:
            workspace_id = get_workspace_id_from_header()
            return _service().cancel(workspace_id, job_id)

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Execution cancel failed")
            return {"error": "Execution cancel failed"}, 500


@executions_ns.route("/<string:job_id>/results")
class ExecutionResults(Resource):
    @token_required
    def get(self, job_id: str):
        try:
            workspace_id = get_workspace_id_from_header()
            return _service().results(workspace_id, job_id)

        except ServiceError as e:
            return _handle_service_error(e)
        except Exception:
            logger.exception("Execution results failed")
            return {"error": "Execution results failed"}, 500
