from __future__ import annotations

from flask import request
from flask_restx import Resource

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.features.flowforge.routes.common import _actor_user_id, _int_query_arg, _service, _workspace_id, flowforge_ns, models


@flowforge_ns.route("/runs")
class FlowForgeRunList(Resource):
    @flowforge_ns.doc(
        summary="List persisted FlowForge workflow runs",
        description=(
            "Returns workspace-scoped workflow runs created by FlowForge runtime intake. This endpoint is "
            "read-only and intended for the operator run list, local QA, and future reporting/MCP read tools. "
            "Use status and mode to narrow the list. Limit defaults to 100 and is capped by the service at "
            "500; offset defaults to 0. Sensitive intake payloads and sensitive event payloads are not returned."
        ),
        params={
            "status": "Optional exact status filter such as waiting, running, completed, failed, or needs_attention.",
            "mode": "Optional exact run mode filter, typically production or test.",
            "limit": "Maximum runs to return. Defaults to 100 and is capped at 500.",
            "offset": "Zero-based run offset. Defaults to 0.",
        },
        responses={
            200: "Workflow runs returned.",
            400: "Missing workspace context.",
            401: "Authentication required.",
            403: "FlowForge feature or role access required.",
        },
    )
    @flowforge_ns.marshal_with(models["workflow_run_list"])
    @token_required
    @require_access("flowforge", role="viewer")
    def get(self):
        try:
            return (
                _service().list_runs(
                    workspace_id=_workspace_id(),
                    status=request.args.get("status"),
                    mode=request.args.get("mode"),
                    limit=_int_query_arg("limit", 100),
                    offset=_int_query_arg("offset", 0),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/runs/<int:run_id>")
@flowforge_ns.param("run_id", "Persisted FlowForge workflow run id.")
class FlowForgeRunDetail(Resource):
    @flowforge_ns.doc(
        summary="Get a persisted FlowForge workflow run",
        description=(
            "Returns a single workspace-scoped workflow run by id. The response contains redacted run context "
            "suitable for operator inspection and future MCP read-only tools. Raw intake payloads and sensitive "
            "runtime payloads are intentionally omitted."
        ),
        responses={
            200: "Workflow run returned.",
            401: "Authentication required.",
            403: "FlowForge feature or role access required.",
            404: "Workflow run not found in this workspace.",
        },
    )
    @flowforge_ns.marshal_with(models["workflow_run"])
    @token_required
    @require_access("flowforge", role="viewer")
    def get(self, run_id: int):
        try:
            run = _service().get_run(workspace_id=_workspace_id(), run_id=run_id)
            if run is None:
                raise ForgeError(f"FlowForge run '{run_id}' was not found.", status_code=404)
            return run, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/runs/<int:run_id>/events")
@flowforge_ns.param("run_id", "Persisted FlowForge workflow run id.")
class FlowForgeRunEventList(Resource):
    @flowforge_ns.doc(
        summary="List persisted FlowForge workflow run events",
        description=(
            "Returns the append-only event timeline for a workspace-scoped workflow run. Events are ordered by "
            "creation time and id. The endpoint returns redacted event payloads only; sensitive event payload "
            "storage is never exposed through this read API."
        ),
        params={"limit": "Maximum events to return. Defaults to 100 and is capped at 500."},
        responses={
            200: "Workflow run events returned.",
            401: "Authentication required.",
            403: "FlowForge feature or role access required.",
        },
    )
    @flowforge_ns.marshal_with(models["workflow_run_event_list"])
    @token_required
    @require_access("flowforge", role="viewer")
    def get(self, run_id: int):
        try:
            return (
                _service().list_run_events(
                    workspace_id=_workspace_id(),
                    run_id=run_id,
                    limit=_int_query_arg("limit", 100),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/runs/<int:run_id>/human-tasks")
@flowforge_ns.param("run_id", "Persisted FlowForge workflow run id.")
class FlowForgeRunHumanTaskList(Resource):
    @flowforge_ns.doc(
        summary="List FlowForge human tasks for a run",
        description=(
            "Returns human-facing tasks attached to a workflow run, including offer, review, manual-assignment, "
            "and needs-attention tasks as those runtime phases are added. This read API is the foundation for "
            "run-detail offer history and operator needs-attention views. It returns redacted response metadata "
            "only and does not expose signed action tokens or sensitive payloads."
        ),
        params={"limit": "Maximum tasks to return. Defaults to 100 and is capped at 500."},
        responses={
            200: "Human tasks returned.",
            401: "Authentication required.",
            403: "FlowForge feature or role access required.",
            404: "Workflow run not found in this workspace.",
        },
    )
    @flowforge_ns.marshal_with(models["human_task_list"])
    @token_required
    @require_access("flowforge", role="viewer")
    def get(self, run_id: int):
        try:
            return (
                _service().list_run_human_tasks(
                    workspace_id=_workspace_id(),
                    run_id=run_id,
                    limit=_int_query_arg("limit", 100),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/runs/<int:run_id>/notifications")
@flowforge_ns.param("run_id", "Persisted FlowForge workflow run id.")
class FlowForgeRunNotificationList(Resource):
    @flowforge_ns.doc(
        summary="List FlowForge notifications for a run",
        description=(
            "Returns notification audit rows for a workflow run. This includes pending, sent, and failed "
            "notification records as later dispatch phases are added. Payload summaries are redacted and should "
            "not contain raw intake or patient-sensitive details."
        ),
        params={"limit": "Maximum notifications to return. Defaults to 100 and is capped at 500."},
        responses={200: "Notifications returned.", 401: "Authentication required.", 403: "FlowForge access required."},
    )
    @flowforge_ns.marshal_with(models["notification_list"])
    @token_required
    @require_access("flowforge", role="viewer")
    def get(self, run_id: int):
        try:
            return (
                _service().list_run_notifications(
                    workspace_id=_workspace_id(),
                    run_id=run_id,
                    limit=_int_query_arg("limit", 100),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/runs/<int:run_id>/no-match-escalations")
@flowforge_ns.param("run_id", "Persisted FlowForge workflow run id.")
class FlowForgeNoMatchEscalationCreate(Resource):
    @flowforge_ns.doc(
        summary="Queue a no-match escalation for a FlowForge run",
        description=(
            "Marks the run as needs_attention, appends a no-match escalation event, and creates pending email "
            "notification audit rows. This endpoint queues notification records only; actual email dispatch is "
            "handled by a later notification worker phase."
        ),
        responses={
            201: "No-match escalation queued.",
            400: "Invalid escalation payload.",
            401: "Authentication required.",
            403: "FlowForge operator access required.",
            404: "Workflow run not found in this workspace.",
        },
    )
    @flowforge_ns.expect(models["no_match_escalation_request"], validate=False)
    @flowforge_ns.marshal_with(models["no_match_escalation_response"])
    @token_required
    @require_access("flowforge", role="operator")
    def post(self, run_id: int):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().create_no_match_escalation(
                    workspace_id=_workspace_id(),
                    run_id=run_id,
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                201,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/runs/<int:run_id>/notes")
@flowforge_ns.param("run_id", "Persisted FlowForge workflow run id.")
class FlowForgeRunNoteCreate(Resource):
    @flowforge_ns.doc(
        summary="Append an operator note to a FlowForge run",
        description=(
            "Adds an operator note to the append-only run timeline. Notes are stored as run events with "
            "event_type=workflow.operator.note so they remain visible in timeline, audit, and future MCP "
            "read paths. This endpoint does not change run status or advance workflow execution. Until "
            "note creation requires flowforge:operator access."
        ),
        responses={
            201: "Operator note event appended.",
            400: "Invalid note payload.",
            401: "Authentication required.",
            403: "FlowForge operator access required.",
            404: "Workflow run not found in this workspace.",
        },
    )
    @flowforge_ns.expect(models["workflow_run_note_request"], validate=False)
    @flowforge_ns.marshal_with(models["workflow_run_event"])
    @token_required
    @require_access("flowforge", role="operator")
    def post(self, run_id: int):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().add_run_note(
                    workspace_id=_workspace_id(),
                    run_id=run_id,
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                201,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
