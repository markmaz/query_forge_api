from __future__ import annotations

from flask import request
from flask_restx import Resource

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.features.flowforge.routes.common import _actor_user_id, _service, _workspace_id, flowforge_ns, models


@flowforge_ns.route("/settings")
class FlowForgeWorkspaceSettings(Resource):
    @flowforge_ns.doc(
        summary="Get FlowForge workspace settings",
        description=(
            "Returns workspace-level FlowForge runtime defaults for retention, offer timeout, test recipients, "
            "and no-match notification recipients. These settings are used by webhook intake, matching/offer "
            "runtime defaults, and operator escalation flows."
        ),
        responses={200: "Settings returned.", 401: "Authentication required.", 403: "FlowForge access required."},
    )
    @flowforge_ns.marshal_with(models["workspace_settings"])
    @token_required
    @require_access("flowforge", role="admin")
    def get(self):
        try:
            return _service().get_workspace_settings(workspace_id=_workspace_id()), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @flowforge_ns.doc(
        summary="Update FlowForge workspace settings",
        description=(
            "Updates workspace-level FlowForge runtime defaults. Retention is capped by the product maximum "
            "stored with the workspace settings row, offer timeout is bounded to prevent runaway pending tasks, "
            "and recipient fields must be arrays of email addresses."
        ),
        responses={
            200: "Settings updated.",
            400: "Invalid settings payload.",
            401: "Authentication required.",
            403: "FlowForge admin access required.",
        },
    )
    @flowforge_ns.expect(models["workspace_settings_update"], validate=False)
    @flowforge_ns.marshal_with(models["workspace_settings"])
    @token_required
    @require_access("flowforge", role="admin")
    def put(self):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().update_workspace_settings(
                    workspace_id=_workspace_id(),
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
