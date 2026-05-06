from __future__ import annotations

from flask import request
from flask_restx import Resource

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.features.flowforge.routes.common import _actor_user_id, _service, _workspace_id, flowforge_ns, models


@flowforge_ns.route("/workflows")
class FlowForgeWorkflowList(Resource):
    @flowforge_ns.doc(
        summary="List FlowForge workflow definitions",
        description=(
            "Returns workflow definitions available to the current workspace. The initial implementation "
            "returns the seeded Therapist Intake Routing workflow while persistence is being designed."
        ),
        responses={
            200: "Workflow definitions returned.",
            400: "Missing workspace context.",
            401: "Authentication required.",
            403: "FlowForge feature or role access required.",
        },
    )
    @flowforge_ns.marshal_list_with(models["workflow_definition"])
    @token_required
    @require_access("flowforge", role="viewer")
    def get(self):
        try:
            return _service().list_definitions(workspace_id=_workspace_id())
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @flowforge_ns.doc(
        summary="Create a persisted FlowForge workflow draft",
        description=(
            "Creates a workspace-scoped workflow definition and its first immutable draft version. The submitted "
            "graph is validated before persistence; invalid graphs are rejected and are not saved."
        ),
        responses={
            201: "Workflow draft created.",
            400: "Invalid workflow payload.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
        },
    )
    @flowforge_ns.expect(models["workflow_definition_create"], validate=False)
    @flowforge_ns.marshal_with(models["workflow_definition"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().create_workflow_definition(
                    workspace_id=_workspace_id(),
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                201,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/workflows/<string:workflow_id>")
@flowforge_ns.param("workflow_id", "Workflow definition id.")
class FlowForgeWorkflowDetail(Resource):
    @flowforge_ns.doc(
        summary="Get a FlowForge workflow definition",
        description="Returns a single workflow definition graph for the current workspace.",
        responses={
            200: "Workflow definition returned.",
            404: "Workflow definition not found.",
        },
    )
    @flowforge_ns.marshal_with(models["workflow_definition"])
    @token_required
    @require_access("flowforge", role="viewer")
    def get(self, workflow_id: str):
        try:
            workflow = _service().get_definition(workspace_id=_workspace_id(), workflow_id=workflow_id)
            if workflow is None:
                raise ForgeError(f"Workflow '{workflow_id}' was not found.", status_code=404)
            return workflow
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @flowforge_ns.doc(
        summary="Archive a persisted FlowForge workflow definition",
        description=(
            "Soft-deletes a workspace-scoped workflow definition by setting its archive metadata. Archived "
            "workflows are removed from normal workflow lists but retained for auditability and future recovery "
            "workflows. Seeded workflows such as the built-in therapist routing example cannot be deleted."
        ),
        responses={
            200: "Workflow definition archived.",
            400: "Workflow id must be a persisted numeric definition id.",
            401: "Authentication required.",
            403: "FlowForge admin access required.",
            404: "Workflow definition not found.",
        },
    )
    @token_required
    @require_access("flowforge", role="admin")
    def delete(self, workflow_id: str):
        try:
            try:
                workflow_definition_id = int(workflow_id)
            except (TypeError, ValueError) as exc:
                raise ForgeError("Only persisted workflow definitions can be deleted.", status_code=400) from exc
            return (
                _service().delete_workflow_definition(
                    workspace_id=_workspace_id(),
                    workflow_definition_id=workflow_definition_id,
                    actor_user_id=_actor_user_id(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/workflows/validate")
class FlowForgeWorkflowValidation(Resource):
    @flowforge_ns.doc(
        summary="Validate a FlowForge workflow graph",
        description=(
            "Validates the node/edge graph shape. Loops are allowed and returned as warnings, not errors, "
            "because FlowForge runtime execution is expected to use state-machine semantics for long-running flows."
        ),
        responses={
            200: "Validation completed.",
            400: "Missing workspace context.",
        },
    )
    @flowforge_ns.marshal_with(models["validation_result"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self):
        try:
            payload = request.get_json(silent=True) or {}
            graph = payload.get("graph", payload) if isinstance(payload, dict) else {}
            return _service().validate_graph(graph=graph), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/workflows/<int:workflow_definition_id>/versions")
@flowforge_ns.param("workflow_definition_id", "Persisted workflow definition id.")
class FlowForgeWorkflowVersionList(Resource):
    @flowforge_ns.doc(
        summary="List persisted FlowForge workflow versions",
        description=(
            "Returns draft/published workflow versions for a persisted workflow definition. This endpoint is "
            "part of the workflow editor hardening path and lets the UI distinguish draft graph state from "
            "immutable published runtime versions."
        ),
        responses={200: "Workflow versions returned.", 401: "Authentication required.", 403: "FlowForge access required."},
    )
    @flowforge_ns.marshal_list_with(models["workflow_version"])
    @token_required
    @require_access("flowforge", role="viewer")
    def get(self, workflow_definition_id: int):
        try:
            return (
                _service().list_workflow_versions(
                    workspace_id=_workspace_id(),
                    workflow_definition_id=workflow_definition_id,
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @flowforge_ns.doc(
        summary="Create a persisted FlowForge workflow draft version",
        description=(
            "Validates and saves a new immutable draft version for an existing workflow definition. This endpoint "
            "does not publish the version; publish remains an explicit admin action."
        ),
        responses={
            201: "Workflow draft version created.",
            400: "Invalid graph payload.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
            404: "Workflow definition not found.",
        },
    )
    @flowforge_ns.expect(models["workflow_version_create"], validate=False)
    @flowforge_ns.marshal_with(models["workflow_version"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self, workflow_definition_id: int):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().create_workflow_version(
                    workspace_id=_workspace_id(),
                    workflow_definition_id=workflow_definition_id,
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                201,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/workflows/<int:workflow_definition_id>/versions/<int:version_id>/publish")
@flowforge_ns.param("workflow_definition_id", "Persisted workflow definition id.")
@flowforge_ns.param("version_id", "Workflow version id to publish.")
class FlowForgeWorkflowVersionPublish(Resource):
    @flowforge_ns.doc(
        summary="Publish a persisted FlowForge workflow version",
        description=(
            "Promotes a valid workflow version to published status and records it as the workflow definition's "
            "latest published version. Publishing requires FlowForge admin access by default; designer publish "
            "can be added later through the workspace setting already present in the schema."
        ),
        responses={
            200: "Workflow version published.",
            400: "Workflow version is not valid.",
            401: "Authentication required.",
            403: "FlowForge admin access required.",
            404: "Workflow version not found.",
        },
    )
    @flowforge_ns.marshal_with(models["workflow_version"])
    @token_required
    @require_access("flowforge", role="admin")
    def post(self, workflow_definition_id: int, version_id: int):
        try:
            return (
                _service().publish_workflow_version(
                    workspace_id=_workspace_id(),
                    workflow_definition_id=workflow_definition_id,
                    version_id=version_id,
                    actor_user_id=_actor_user_id(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/workflows/<string:workflow_id>/run-inspector")
@flowforge_ns.param("workflow_id", "Workflow definition id.")
class FlowForgeRunInspector(Resource):
    @flowforge_ns.doc(
        summary="Get the FlowForge run inspector placeholder",
        description=(
            "Returns event-first placeholder data for the selected workflow. This is intentionally read-only "
            "until durable workflow run persistence and execution simulation are implemented."
        ),
        responses={
            200: "Run inspector placeholder returned.",
            404: "Workflow definition not found.",
        },
    )
    @flowforge_ns.marshal_with(models["run_inspector"])
    @token_required
    @require_access("flowforge", role="viewer")
    def get(self, workflow_id: str):
        try:
            inspector = _service().get_run_inspector(workspace_id=_workspace_id(), workflow_id=workflow_id)
            if inspector is None:
                raise ForgeError(f"Workflow '{workflow_id}' was not found.", status_code=404)
            return inspector, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
