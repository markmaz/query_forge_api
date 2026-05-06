from __future__ import annotations

from flask import request
from flask_restx import Resource

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.features.flowforge.routes.common import _actor_user_id, _int_query_arg, _service, _workspace_id, flowforge_ns, models


@flowforge_ns.route("/communication-templates")
class FlowForgeCommunicationTemplateList(Resource):
    @flowforge_ns.doc(
        summary="List FlowForge communication templates",
        description="Returns workspace-scoped communication templates, optionally filtered by status, purpose, channel, or resource set.",
        responses={
            200: "Communication templates returned.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
        },
    )
    @flowforge_ns.marshal_list_with(models["communication_template"])
    @token_required
    @require_access("flowforge", role="designer")
    def get(self):
        try:
            resource_set_id = request.args.get("resource_set_id")
            return (
                _service().list_communication_templates(
                    workspace_id=_workspace_id(),
                    status=request.args.get("status"),
                    purpose=request.args.get("purpose"),
                    channel=request.args.get("channel"),
                    resource_set_id=_int_query_arg("resource_set_id", 0) if resource_set_id else None,
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @flowforge_ns.doc(
        summary="Create a FlowForge communication template",
        description="Creates a draft communication template after validating its structured subject and body blocks.",
        responses={
            201: "Communication template created.",
            400: "Invalid template payload.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
        },
    )
    @flowforge_ns.expect(models["communication_template_upsert"], validate=False)
    @flowforge_ns.marshal_with(models["communication_template"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().create_communication_template(
                    workspace_id=_workspace_id(),
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                201,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/communication-templates/<int:template_id>")
@flowforge_ns.param("template_id", "Communication template id.")
class FlowForgeCommunicationTemplateDetail(Resource):
    @flowforge_ns.doc(
        summary="Get a FlowForge communication template",
        responses={
            200: "Communication template returned.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
            404: "Communication template not found.",
        },
    )
    @flowforge_ns.marshal_with(models["communication_template"])
    @token_required
    @require_access("flowforge", role="designer")
    def get(self, template_id: int):
        try:
            template = _service().get_communication_template(workspace_id=_workspace_id(), template_id=template_id)
            if template is None:
                raise ForgeError(f"Communication template '{template_id}' was not found.", status_code=404)
            return template, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @flowforge_ns.doc(
        summary="Update a FlowForge communication template",
        responses={
            200: "Communication template updated.",
            400: "Invalid template payload.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
            404: "Communication template not found.",
        },
    )
    @flowforge_ns.expect(models["communication_template_upsert"], validate=False)
    @flowforge_ns.marshal_with(models["communication_template"])
    @token_required
    @require_access("flowforge", role="designer")
    def patch(self, template_id: int):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().update_communication_template(
                    workspace_id=_workspace_id(),
                    template_id=template_id,
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/communication-templates/<int:template_id>/validate")
@flowforge_ns.param("template_id", "Communication template id.")
class FlowForgeCommunicationTemplateValidation(Resource):
    @flowforge_ns.doc(
        summary="Validate and preview a FlowForge communication template",
        responses={
            200: "Communication template validation returned.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
            404: "Communication template not found.",
        },
    )
    @flowforge_ns.marshal_with(models["communication_template_validation"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self, template_id: int):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().validate_communication_template(
                    workspace_id=_workspace_id(),
                    template_id=template_id,
                    payload=payload if isinstance(payload, dict) else {},
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/communication-templates/<int:template_id>/activate")
@flowforge_ns.param("template_id", "Communication template id.")
class FlowForgeCommunicationTemplateActivation(Resource):
    @flowforge_ns.doc(
        summary="Activate a valid FlowForge communication template",
        responses={
            200: "Communication template activated.",
            400: "Communication template is invalid.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
            404: "Communication template not found.",
        },
    )
    @flowforge_ns.marshal_with(models["communication_template"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self, template_id: int):
        try:
            return (
                _service().activate_communication_template(
                    workspace_id=_workspace_id(),
                    template_id=template_id,
                    actor_user_id=_actor_user_id(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
