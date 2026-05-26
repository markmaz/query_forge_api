from __future__ import annotations

from flask import request
from flask_restx import Resource

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.features.flowforge.routes.common import _actor_user_id, _service, _workspace_id, flowforge_ns, models


@flowforge_ns.route("/integrations")
class FlowForgeIntegrationList(Resource):
    @flowforge_ns.doc(
        summary="List FlowForge integrations",
        description=(
            "Returns workspace-scoped FlowForge integration configurations. The response includes provider, "
            "mode, public webhook id/path/url, field mapping, and safe settings. Stored webhook secret hashes "
            "are never returned. Use provider=jotform or provider=webhook to filter by integration source."
        ),
        params={"provider": "Optional provider filter. Supported values include jotform and webhook."},
        responses={
            200: "Integrations returned.",
            400: "Missing workspace context.",
            401: "Authentication required.",
            403: "FlowForge feature or role access required.",
        },
    )
    @flowforge_ns.marshal_list_with(models["integration_config"])
    @token_required
    @require_access("flowforge", role="designer")
    def get(self):
        try:
            return (
                _service().list_integrations(
                    workspace_id=_workspace_id(),
                    provider=request.args.get("provider"),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/integrations/jotform")
class FlowForgeJotformIntegrationCreate(Resource):
    @flowforge_ns.doc(
        summary="Create a Jotform integration",
        description=(
            "Creates a persisted workspace-scoped Jotform integration configuration with an opaque public "
            "webhook id and a generated secret. The plaintext secret is returned only once in this create "
            "response; only a hash is stored. The integration can run in production or test mode. Trigger "
            "configuration, persisted webhook intake, and replay are implemented in later Phase 5 slices."
        ),
        responses={
            201: "Jotform integration created.",
            400: "Invalid integration payload.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
        },
    )
    @flowforge_ns.marshal_with(models["integration_config_create_response"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().create_jotform_integration(
                    workspace_id=_workspace_id(),
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                201,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/integrations/webhook")
class FlowForgeGenericWebhookIntegrationCreate(Resource):
    @flowforge_ns.doc(
        summary="Create a generic webhook integration",
        description=(
            "Creates a workspace-scoped generic webhook integration with an opaque public webhook id and a "
            "generated secret. The plaintext secret is returned only once in this create response; only a hash "
            "is stored. Generic webhooks are for external systems that can POST structured JSON directly to "
            "FlowForge without a provider-specific adapter."
        ),
        responses={
            201: "Generic webhook integration created.",
            400: "Invalid integration payload.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
        },
    )
    @flowforge_ns.marshal_with(models["integration_config_create_response"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().create_webhook_integration(
                    workspace_id=_workspace_id(),
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                201,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/integrations/file-watch")
class FlowForgeFileWatchIntegrationCreate(Resource):
    @flowforge_ns.doc(
        summary="Create a file watch integration",
        description=(
            "Creates a workspace-scoped file watch integration catalog entry. File watch integrations define "
            "the allowed file source key, actions/events, and source fields available to workflow file watch "
            "trigger nodes. They do not create a public webhook endpoint."
        ),
        responses={
            201: "File watch integration created.",
            400: "Invalid integration payload.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
        },
    )
    @flowforge_ns.marshal_with(models["integration_config_create_response"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().create_file_watch_integration(
                    workspace_id=_workspace_id(),
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                201,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/integrations/<int:integration_config_id>/triggers")
@flowforge_ns.param("integration_config_id", "Integration config id whose workflow triggers should be managed.")
class FlowForgeIntegrationTriggerList(Resource):
    @flowforge_ns.doc(
        summary="List FlowForge integration triggers",
        description=(
            "Returns workflow trigger rules for a workspace integration. Triggers define which workflow "
            "definition/version should start when the integration receives an event, plus priority, matching "
            "policy, optional conditional criteria, field mapping, and no-match configuration. This endpoint "
            "does not execute triggers; webhook runtime evaluation is implemented in a later phase."
        ),
        responses={
            200: "Integration triggers returned.",
            401: "Authentication required.",
            403: "FlowForge feature or role access required.",
            404: "Integration not found in this workspace.",
        },
    )
    @flowforge_ns.marshal_list_with(models["integration_trigger"])
    @token_required
    @require_access("flowforge", role="designer")
    def get(self, integration_config_id: int):
        try:
            return (
                _service().list_integration_triggers(
                    workspace_id=_workspace_id(),
                    integration_config_id=integration_config_id,
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @flowforge_ns.doc(
        summary="Create a FlowForge integration trigger",
        description=(
            "Creates a persisted trigger for an integration. A trigger connects an inbound integration event "
            "to a workflow definition and either a pinned workflow version or the latest published version. "
            "Pinned triggers require workflow_version_id. Conditional triggers require a non-empty condition "
            "object. The field_mapping object controls how provider payload fields become workflow intake "
            "context. The no_match_config object stores recipient/escalation behavior for future runtime phases."
        ),
        responses={
            201: "Integration trigger created.",
            400: "Invalid trigger payload.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
            404: "Integration not found in this workspace.",
        },
    )
    @flowforge_ns.marshal_with(models["integration_trigger"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self, integration_config_id: int):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().create_integration_trigger(
                    workspace_id=_workspace_id(),
                    integration_config_id=integration_config_id,
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                201,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/integrations/<int:integration_config_id>/workflow-value-schema/draft")
@flowforge_ns.param("integration_config_id", "Integration config id whose source fields should generate a workflow value schema draft.")
class FlowForgeIntegrationWorkflowValueSchemaDraft(Resource):
    @flowforge_ns.doc(
        summary="Draft a workflow value schema from integration source fields",
        description=(
            "Generates editable Workflow Studio value fields from the integration's configured source fields. "
            "The response is not persisted until PUT /workflow-value-schema is called."
        ),
        responses={
            200: "Workflow value schema draft returned.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
            404: "Integration not found in this workspace.",
        },
    )
    @flowforge_ns.marshal_with(models["workflow_value_schema"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self, integration_config_id: int):
        try:
            return (
                _service().draft_integration_workflow_value_schema(
                    workspace_id=_workspace_id(),
                    integration_config_id=integration_config_id,
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/integrations/<int:integration_config_id>/workflow-value-schema")
@flowforge_ns.param("integration_config_id", "Integration config id whose workflow value schema should be updated.")
class FlowForgeIntegrationWorkflowValueSchema(Resource):
    @flowforge_ns.doc(
        summary="Update an integration workflow value schema",
        description=(
            "Persists the governed clean workflow values for an integration. Map/Transform actions use these "
            "values as dropdown targets and may map one source field to multiple values or combine multiple "
            "source fields through supported transforms."
        ),
        responses={
            200: "Integration returned with updated workflow value schema.",
            400: "Invalid schema payload.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
            404: "Integration not found in this workspace.",
        },
    )
    @flowforge_ns.marshal_with(models["integration_config"])
    @token_required
    @require_access("flowforge", role="designer")
    def put(self, integration_config_id: int):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().update_integration_workflow_value_schema(
                    workspace_id=_workspace_id(),
                    integration_config_id=integration_config_id,
                    payload=payload if isinstance(payload, dict) else {},
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
