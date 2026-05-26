from __future__ import annotations

from flask import request
from flask_restx import Resource

from app.decorators.rbac import require_access, require_feature
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.features.flowforge.routes.common import _actor_user_id, _effective_roles, _service, _workspace_id, flowforge_ns, models


@flowforge_ns.route("/workflows")
class FlowForgeWorkflowList(Resource):
    @flowforge_ns.doc(
        summary="List FlowForge workflow definitions",
        description=(
            "Returns persisted workflow definitions available to the current workspace. Starter templates are "
            "chosen explicitly in the Designer when creating a new workflow."
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
    @require_feature("flowforge")
    def get(self):
        try:
            return _service().list_definitions(
                workspace_id=_workspace_id(),
                actor_user_id=_actor_user_id(),
                effective_roles=_effective_roles(),
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @flowforge_ns.doc(
        summary="Create a persisted FlowForge workflow draft",
        description=(
            "Creates a workspace-scoped workflow definition and its first immutable draft version. The submitted "
            "graph is validated before persistence; incomplete drafts are saved with invalid validation status and "
            "cannot be published until corrected."
        ),
        responses={
            201: "Workflow draft created.",
            400: "Invalid workflow payload.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
        },
    )
    @flowforge_ns.expect(models["workflow_definition_create"], validate=False)
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


@flowforge_ns.route("/workflows/run-as-principals")
class FlowForgeWorkflowRunAsPrincipals(Resource):
    @flowforge_ns.doc(
        summary="List available Workflow Studio run-as principals",
        description="Returns user, workspace, and service principals that can be assigned to workflow runs.",
        responses={200: "Run-as principals returned.", 401: "Authentication required.", 403: "FlowForge access required."},
    )
    @flowforge_ns.marshal_with(models["workflow_run_as_principals"])
    @token_required
    @require_feature("flowforge")
    def get(self):
        try:
            return (
                _service().list_workflow_run_as_principals(
                    workspace_id=_workspace_id(),
                    actor_user_id=_actor_user_id(),
                ),
                200,
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
    @require_feature("flowforge")
    def get(self, workflow_id: str):
        try:
            workflow = _service().get_definition(
                workspace_id=_workspace_id(),
                workflow_id=workflow_id,
                actor_user_id=_actor_user_id(),
                effective_roles=_effective_roles(),
            )
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
            "workflows."
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
    @require_feature("flowforge")
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
                    effective_roles=_effective_roles(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/workflows/<int:workflow_definition_id>/permissions")
@flowforge_ns.param("workflow_definition_id", "Persisted workflow definition id.")
class FlowForgeWorkflowPermissions(Resource):
    @flowforge_ns.doc(
        summary="Get Workflow Studio object permissions",
        description="Returns active ACL grants for a workflow definition. Requires manage permission on the workflow.",
        responses={200: "Workflow permissions returned.", 403: "Manage permission required.", 404: "Workflow not found."},
    )
    @flowforge_ns.marshal_with(models["workflow_permissions"])
    @token_required
    @require_feature("flowforge")
    def get(self, workflow_definition_id: int):
        try:
            return (
                _service().get_workflow_permissions(
                    workspace_id=_workspace_id(),
                    workflow_definition_id=workflow_definition_id,
                    actor_user_id=_actor_user_id(),
                    effective_roles=_effective_roles(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @flowforge_ns.doc(
        summary="Update Workflow Studio object permissions",
        description="Grants, updates, or revokes workflow ACL entries. Requires manage permission on the workflow.",
        responses={200: "Workflow permissions updated.", 400: "Invalid permission payload.", 403: "Manage permission required."},
    )
    @flowforge_ns.expect(models["workflow_permissions_update"], validate=False)
    @flowforge_ns.marshal_with(models["workflow_permissions"])
    @token_required
    @require_feature("flowforge")
    def put(self, workflow_definition_id: int):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().update_workflow_permissions(
                    workspace_id=_workspace_id(),
                    workflow_definition_id=workflow_definition_id,
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                    effective_roles=_effective_roles(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/workflows/<int:workflow_definition_id>/owner")
@flowforge_ns.param("workflow_definition_id", "Persisted workflow definition id.")
class FlowForgeWorkflowOwner(Resource):
    @flowforge_ns.doc(
        summary="Update Workflow Studio workflow owner",
        description="Reassigns workflow ownership and grants the new owner owner-level object permission.",
        responses={200: "Workflow owner updated.", 400: "Invalid owner payload.", 403: "Manage permission required."},
    )
    @flowforge_ns.expect(models["workflow_owner_update"], validate=False)
    @flowforge_ns.marshal_with(models["workflow_definition"])
    @token_required
    @require_feature("flowforge")
    def put(self, workflow_definition_id: int):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().update_workflow_owner(
                    workspace_id=_workspace_id(),
                    workflow_definition_id=workflow_definition_id,
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                    effective_roles=_effective_roles(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/workflows/<int:workflow_definition_id>/metadata")
@flowforge_ns.param("workflow_definition_id", "Persisted workflow definition id.")
class FlowForgeWorkflowMetadata(Resource):
    @flowforge_ns.doc(
        summary="Update Workflow Studio workflow metadata",
        description="Updates the workflow display name and description. Requires manage permission on the workflow.",
        responses={200: "Workflow metadata updated.", 400: "Invalid metadata payload.", 403: "Manage permission required."},
    )
    @flowforge_ns.expect(models["workflow_metadata_update"], validate=False)
    @flowforge_ns.marshal_with(models["workflow_definition"])
    @token_required
    @require_feature("flowforge")
    def put(self, workflow_definition_id: int):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().update_workflow_metadata(
                    workspace_id=_workspace_id(),
                    workflow_definition_id=workflow_definition_id,
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                    effective_roles=_effective_roles(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/workflows/<int:workflow_definition_id>/run-as")
@flowforge_ns.param("workflow_definition_id", "Persisted workflow definition id.")
class FlowForgeWorkflowRunAs(Resource):
    @flowforge_ns.doc(
        summary="Update Workflow Studio run-as principal",
        description="Sets the principal captured by future workflow runs. Production publish requires a service or workspace principal.",
        responses={200: "Workflow run-as principal updated.", 400: "Invalid principal payload.", 403: "Manage permission required."},
    )
    @flowforge_ns.expect(models["workflow_run_as_update"], validate=False)
    @flowforge_ns.marshal_with(models["workflow_definition"])
    @token_required
    @require_feature("flowforge")
    def put(self, workflow_definition_id: int):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().update_workflow_run_as(
                    workspace_id=_workspace_id(),
                    workflow_definition_id=workflow_definition_id,
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                    effective_roles=_effective_roles(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/workflows/<int:workflow_definition_id>/run")
@flowforge_ns.param("workflow_definition_id", "Persisted workflow definition id.")
class FlowForgeWorkflowManualRun(Resource):
    @flowforge_ns.doc(
        summary="Start a Workflow Studio workflow run manually",
        description="Creates a run from the latest published workflow version and queues runtime dispatch.",
        responses={201: "Workflow run created.", 400: "Workflow is not runnable.", 403: "Run permission required."},
    )
    @flowforge_ns.expect(models["workflow_manual_run_request"], validate=False)
    @flowforge_ns.marshal_with(models["workflow_manual_run"])
    @token_required
    @require_feature("flowforge")
    def post(self, workflow_definition_id: int):
        try:
            payload = request.get_json(silent=True) or {}
            result = _service().start_workflow_run(
                workspace_id=_workspace_id(),
                workflow_definition_id=workflow_definition_id,
                payload=payload if isinstance(payload, dict) else {},
                actor_user_id=_actor_user_id(),
                effective_roles=_effective_roles(),
            )
            return result, 201 if result.get("created") else 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/workflows/<int:workflow_definition_id>/readiness")
@flowforge_ns.param("workflow_definition_id", "Persisted workflow definition id.")
class FlowForgeWorkflowReadiness(Resource):
    @flowforge_ns.doc(
        summary="Get Workflow Studio production readiness",
        description=(
            "Returns backend-computed readiness for the persisted workflow lifecycle: draft save, graph validation, "
            "publish, runtime, inspection, and reporting. This is the durable readiness contract used by the Studio UI."
        ),
        responses={200: "Workflow readiness returned.", 403: "View permission required.", 404: "Workflow not found."},
    )
    @flowforge_ns.marshal_with(models["workflow_readiness"])
    @token_required
    @require_feature("flowforge")
    def get(self, workflow_definition_id: int):
        try:
            return (
                _service().get_workflow_readiness(
                    workspace_id=_workspace_id(),
                    workflow_definition_id=workflow_definition_id,
                    actor_user_id=_actor_user_id(),
                    effective_roles=_effective_roles(),
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
            return _service().validate_graph(graph=graph, workspace_id=_workspace_id()), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/workflows/ai-drafts")
class FlowForgeWorkflowAIDraft(Resource):
    @flowforge_ns.doc(
        summary="Generate a FlowForge workflow graph AI draft",
        description=(
            "Uses the workspace FlowForge LLM role to generate or modify the current designer graph from "
            "plain-language instructions. The generated graph is returned with validation results for local review."
        ),
        responses={
            201: "Workflow graph draft generated.",
            400: "Invalid draft request.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
        },
    )
    @flowforge_ns.expect(models["workflow_ai_draft_request"], validate=False)
    @token_required
    @require_access("flowforge", role="designer")
    def post(self):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().create_workflow_ai_draft(
                    workspace_id=_workspace_id(),
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                201,
            )
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
    @require_feature("flowforge")
    def get(self, workflow_definition_id: int):
        try:
            return (
                _service().list_workflow_versions(
                    workspace_id=_workspace_id(),
                    workflow_definition_id=workflow_definition_id,
                    actor_user_id=_actor_user_id(),
                    effective_roles=_effective_roles(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @flowforge_ns.doc(
        summary="Create a persisted FlowForge workflow draft version",
        description=(
            "Validates and saves a new immutable draft version for an existing workflow definition. This endpoint "
            "does not publish the version; invalid drafts are saved with validation results, and publish remains "
            "an explicit admin action for valid versions."
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
    @require_feature("flowforge")
    def post(self, workflow_definition_id: int):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().create_workflow_version(
                    workspace_id=_workspace_id(),
                    workflow_definition_id=workflow_definition_id,
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                    effective_roles=_effective_roles(),
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
    @require_feature("flowforge")
    def post(self, workflow_definition_id: int, version_id: int):
        try:
            return (
                _service().publish_workflow_version(
                    workspace_id=_workspace_id(),
                    workflow_definition_id=workflow_definition_id,
                    version_id=version_id,
                    actor_user_id=_actor_user_id(),
                    effective_roles=_effective_roles(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/workflows/<string:workflow_id>/run-inspector")
@flowforge_ns.param("workflow_id", "Workflow definition id.")
class FlowForgeRunInspector(Resource):
    @flowforge_ns.doc(
        summary="Get the FlowForge workflow design preview",
        description=(
            "Returns a read-only design-time preview for the selected workflow graph. Persisted run history "
            "is available through the run detail endpoints after a workflow starts."
        ),
        responses={
            200: "Workflow design preview returned.",
            404: "Workflow definition not found.",
        },
    )
    @flowforge_ns.marshal_with(models["run_inspector"])
    @token_required
    @require_feature("flowforge")
    def get(self, workflow_id: str):
        try:
            workflow = _service().get_definition(
                workspace_id=_workspace_id(),
                workflow_id=workflow_id,
                actor_user_id=_actor_user_id(),
                effective_roles=_effective_roles(),
            )
            if workflow is None:
                raise ForgeError(f"Workflow '{workflow_id}' was not found.", status_code=404)
            inspector = _service().get_run_inspector(workspace_id=_workspace_id(), workflow_id=workflow_id)
            if inspector is None:
                raise ForgeError(f"Workflow '{workflow_id}' was not found.", status_code=404)
            return inspector, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
