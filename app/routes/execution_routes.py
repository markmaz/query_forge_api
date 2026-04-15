from __future__ import annotations

import logging
from typing import Any, Callable, Dict

from flask import request
from flask_restx import Namespace
from flask_restx import Resource

from app.decorators.security import token_required
from app.decorators.rbac import require_access
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import extract_workspace_id
from app.services.execution_service import ExecutionService

logger = logging.getLogger(__name__)
executions_ns = Namespace("executions", description="Databricks SQL executions")


def _service() -> ExecutionService:
    return ExecutionService()


def _service_error(error: ForgeError):
    return {"error": str(error)}, getattr(error, "status_code", 400) or 400


def _run(handler: Callable[[], Any]):
    return handler()


def _json_payload() -> Dict[str, Any]:
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        raise ForgeError("Invalid JSON body", status_code=400)
    return payload


@executions_ns.route("/start")
class ExecutionStart(Resource):
    @token_required
    @require_access("exports")
    def post(self):
        def handler():
            workspace_id = extract_workspace_id()
            payload = _json_payload()
            query_params = dict(request.args)
            return _service().start(workspace_id, payload, query_params)

        return _run(handler)


@executions_ns.route("/<string:job_id>/status")
class ExecutionStatus(Resource):
    @token_required
    @require_access("exports")
    def get(self, job_id: str):
        def handler():
            return _service().status(extract_workspace_id(), job_id)

        return _run(handler)


@executions_ns.route("/<string:job_id>/cancel")
class ExecutionCancel(Resource):
    @token_required
    @require_access("exports")
    def post(self, job_id: str):
        def handler():
            return _service().cancel(extract_workspace_id(), job_id)

        return _run(handler)


@executions_ns.route("/<string:job_id>/results")
class ExecutionResults(Resource):
    @token_required
    @require_access("exports")
    def get(self, job_id: str):
        def handler():
            return _service().results(extract_workspace_id(), job_id)

        return _run(handler)
