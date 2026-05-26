from __future__ import annotations

import hashlib

from flask import request
from flask_restx import Resource

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.features.flowforge.routes.common import _actor_user_id, _int_query_arg, _service, _workspace_id, flowforge_ns, models
from app.services.auth.rate_limit_service import RateLimitService


def _enforce_signed_action_rate_limit(*, token: str, action: str) -> None:
    token_fingerprint = hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()[:24]
    source = str(request.remote_addr or "unknown").strip() or "unknown"
    RateLimitService().enforce(
        scope=f"flowforge:signed_action:{action}",
        identifier=f"{source}:{token_fingerprint}",
        max_attempts=20 if action == "details" else 8,
        window_s=60,
        message="Too many signed action attempts. Please try again later.",
    )


@flowforge_ns.route("/human-tasks")
class FlowForgeHumanTaskQueue(Resource):
    @flowforge_ns.doc(
        summary="List FlowForge human tasks for operator queues",
        description=(
            "Returns workspace-scoped human tasks independent of run status. This is the operator queue "
            "surface for pending approval gates and other human review work. Use task_type=approval and "
            "status=pending,waiting to find approval gates that need a decision."
        ),
        params={
            "task_type": "Optional exact task type filter, such as approval or offer.",
            "status": "Optional comma-separated task statuses, such as pending,waiting.",
            "limit": "Maximum tasks to return. Defaults to 100 and is capped at 500.",
            "offset": "Zero-based task offset. Defaults to 0.",
        },
        responses={
            200: "Human tasks returned.",
            401: "Authentication required.",
            403: "FlowForge operator access required.",
        },
    )
    @flowforge_ns.marshal_with(models["human_task_queue"])
    @token_required
    @require_access("flowforge", role="operator")
    def get(self):
        try:
            return (
                _service().list_human_tasks(
                    workspace_id=_workspace_id(),
                    task_type=request.args.get("task_type"),
                    status=request.args.get("status"),
                    limit=_int_query_arg("limit", 100),
                    offset=_int_query_arg("offset", 0),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/human-tasks/<int:human_task_id>/signed-actions")
@flowforge_ns.param("human_task_id", "Human task id receiving a public signed action token.")
class FlowForgeHumanTaskSignedActionCreate(Resource):
    @flowforge_ns.doc(
        summary="Create a public signed action token for a human task",
        description=(
            "Creates a one-time public action token for a human task. The plaintext token is returned only in "
            "this response and only its SHA-256 hash is stored. This is intended for offer/response emails and "
            "does not send a notification by itself."
        ),
        responses={
            201: "Signed action token created.",
            400: "Invalid token creation payload.",
            401: "Authentication required.",
            403: "FlowForge operator access required.",
            404: "Human task not found in this workspace.",
        },
    )
    @flowforge_ns.expect(models["signed_action_create_request"], validate=False)
    @flowforge_ns.marshal_with(models["signed_action_create_response"])
    @token_required
    @require_access("flowforge", role="operator")
    def post(self, human_task_id: int):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().create_signed_action_token(
                    workspace_id=_workspace_id(),
                    human_task_id=human_task_id,
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                201,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/human-tasks/<int:human_task_id>/approve")
@flowforge_ns.param("human_task_id", "Approval human task id receiving an authenticated approval decision.")
class FlowForgeApprovalTaskApprove(Resource):
    @flowforge_ns.doc(
        summary="Approve a FlowForge approval task",
        description=(
            "Marks an approval human task as approved, records an auditable user decision, and resumes the "
            "workflow run from the approval node. This endpoint is for authenticated FlowForge operators; "
            "public signed-action links are not used for governed import/export approval gates."
        ),
        responses={
            200: "Approval accepted and workflow resumed.",
            400: "Invalid approval task or decision payload.",
            401: "Authentication required.",
            403: "FlowForge operator access required.",
            404: "Human task not found in this workspace.",
            409: "Approval task is no longer pending.",
        },
    )
    @flowforge_ns.expect(models["approval_decision_request"], validate=False)
    @flowforge_ns.marshal_with(models["approval_decision_response"])
    @token_required
    @require_access("flowforge", role="operator")
    def post(self, human_task_id: int):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().complete_approval_task(
                    workspace_id=_workspace_id(),
                    human_task_id=human_task_id,
                    action="approve",
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/human-tasks/<int:human_task_id>/decline")
@flowforge_ns.param("human_task_id", "Approval human task id receiving an authenticated decline decision.")
class FlowForgeApprovalTaskDecline(Resource):
    @flowforge_ns.doc(
        summary="Decline a FlowForge approval task",
        description=(
            "Marks an approval human task as declined, records an auditable user decision, and advances the "
            "workflow through a configured decline branch. If no decline branch exists, the run is marked "
            "failed so guarded import/export side effects do not continue silently."
        ),
        responses={
            200: "Approval declined and workflow branched or failed.",
            400: "Invalid approval task or decision payload.",
            401: "Authentication required.",
            403: "FlowForge operator access required.",
            404: "Human task not found in this workspace.",
            409: "Approval task is no longer pending.",
        },
    )
    @flowforge_ns.expect(models["approval_decision_request"], validate=False)
    @flowforge_ns.marshal_with(models["approval_decision_response"])
    @token_required
    @require_access("flowforge", role="operator")
    def post(self, human_task_id: int):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().complete_approval_task(
                    workspace_id=_workspace_id(),
                    human_task_id=human_task_id,
                    action="decline",
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/public/actions/<string:token>")
@flowforge_ns.param("token", "Opaque public signed action token.")
class FlowForgePublicSignedActionDetail(Resource):
    @flowforge_ns.doc(
        summary="Get public signed action details",
        description=(
            "Validates a public signed action token and returns minimal task/action metadata for the signed "
            "response page. This endpoint intentionally does not require QueryForge bearer authentication and "
            "does not expose intake details, run context, or sensitive payloads."
        ),
        responses={
            200: "Signed action details returned.",
            404: "Token not found.",
            409: "Token already used/revoked or task no longer pending.",
            410: "Token expired.",
        },
    )
    @flowforge_ns.marshal_with(models["public_signed_action"])
    def get(self, token: str):
        try:
            _enforce_signed_action_rate_limit(token=token, action="details")
            return _service().get_signed_action_details(token=token), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/public/actions/<string:token>/accept")
@flowforge_ns.param("token", "Opaque public signed action token.")
class FlowForgePublicSignedActionAccept(Resource):
    @flowforge_ns.doc(
        summary="Accept a public signed action",
        description="Marks a pending signed human task as accepted and appends a redacted run event.",
        responses={200: "Action accepted.", 400: "Invalid action.", 404: "Token not found.", 409: "Token not usable."},
    )
    @flowforge_ns.marshal_with(models["public_signed_action_result"])
    def post(self, token: str):
        try:
            _enforce_signed_action_rate_limit(token=token, action="complete")
            payload = request.get_json(silent=True) or {}
            return (
                _service().complete_signed_action(
                    token=token,
                    action="accept",
                    payload=payload if isinstance(payload, dict) else {},
                    source_ip=request.remote_addr,
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/public/actions/<string:token>/decline")
@flowforge_ns.param("token", "Opaque public signed action token.")
class FlowForgePublicSignedActionDecline(Resource):
    @flowforge_ns.doc(
        summary="Decline a public signed action",
        description="Marks a pending signed human task as declined and appends a redacted run event.",
        responses={200: "Action declined.", 400: "Invalid action.", 404: "Token not found.", 409: "Token not usable."},
    )
    @flowforge_ns.marshal_with(models["public_signed_action_result"])
    def post(self, token: str):
        try:
            _enforce_signed_action_rate_limit(token=token, action="complete")
            payload = request.get_json(silent=True) or {}
            return (
                _service().complete_signed_action(
                    token=token,
                    action="decline",
                    payload=payload if isinstance(payload, dict) else {},
                    source_ip=request.remote_addr,
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
