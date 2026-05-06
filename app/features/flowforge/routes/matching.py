from __future__ import annotations

from flask import request
from flask_restx import Resource

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.features.flowforge.routes.common import _actor_user_id, _service, _workspace_id, flowforge_ns, models


@flowforge_ns.route("/matching-policies/validate")
class FlowForgeMatchingPolicyValidation(Resource):
    @flowforge_ns.doc(
        summary="Validate a FlowForge matching policy draft",
        description=(
            "Validates deterministic matching policy JSON before simulation or publish. The validator checks "
            "the first supported policy shape and operator set. It does not publish or persist the policy. "
            "This endpoint is intended for the guided rule UI and future LLM-assisted draft review."
        ),
        responses={
            200: "Policy validation completed.",
            400: "Invalid validation request.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
        },
    )
    @flowforge_ns.marshal_with(models["matching_policy_validation"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().validate_matching_policy(
                    workspace_id=_workspace_id(),
                    payload=payload if isinstance(payload, dict) else {},
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/matching-policies")
class FlowForgeMatchingPolicyList(Resource):
    @flowforge_ns.doc(
        summary="List FlowForge matching policies",
        description=(
            "Returns workspace-scoped matching policy headers. Matching policies define the deterministic, "
            "explainable eligibility and ranking rules used by FlowForge workflow steps. This list intentionally "
            "returns policy metadata only; use the policy-version endpoints to inspect saved rule JSON."
        ),
        responses={
            200: "Matching policies returned.",
            400: "Missing workspace context.",
            401: "Authentication required.",
            403: "FlowForge feature or role access required.",
        },
    )
    @flowforge_ns.marshal_list_with(models["matching_policy"])
    @token_required
    @require_access("flowforge", role="designer")
    def get(self):
        try:
            return _service().list_matching_policies(workspace_id=_workspace_id()), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @flowforge_ns.doc(
        summary="Create a FlowForge matching policy",
        description=(
            "Creates a workspace-scoped matching policy header and optionally saves the first draft policy "
            "version when a policy JSON payload is supplied. The policy JSON is validated before persistence. "
            "Publishing is intentionally not implemented in this phase and remains an explicit future action."
        ),
        responses={
            201: "Matching policy created.",
            400: "Invalid matching policy payload.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
        },
    )
    @flowforge_ns.marshal_with(models["matching_policy"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().create_matching_policy(
                    workspace_id=_workspace_id(),
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                201,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/matching-policies/<int:matching_policy_id>")
@flowforge_ns.param("matching_policy_id", "Matching policy id.")
class FlowForgeMatchingPolicyDetail(Resource):
    @flowforge_ns.doc(
        summary="Get a FlowForge matching policy",
        description="Returns a workspace-scoped matching policy header by id. Versions are listed separately.",
        responses={
            200: "Matching policy returned.",
            401: "Authentication required.",
            403: "FlowForge feature or role access required.",
            404: "Matching policy not found.",
        },
    )
    @flowforge_ns.marshal_with(models["matching_policy"])
    @token_required
    @require_access("flowforge", role="designer")
    def get(self, matching_policy_id: int):
        try:
            policy = _service().get_matching_policy(workspace_id=_workspace_id(), matching_policy_id=matching_policy_id)
            if policy is None:
                raise ForgeError(f"Matching policy '{matching_policy_id}' was not found.", status_code=404)
            return policy, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @flowforge_ns.doc(
        summary="Delete a FlowForge matching policy",
        description=(
            "Soft-deletes a workspace-scoped matching policy by archiving the policy header and marking its "
            "non-published versions deleted. Policies with published versions are protected because published "
            "versions may be referenced by auditable workflow runtime behavior."
        ),
        responses={
            200: "Matching policy deleted.",
            400: "Matching policy has published versions and cannot be deleted.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
            404: "Matching policy not found.",
        },
    )
    @token_required
    @require_access("flowforge", role="designer")
    def delete(self, matching_policy_id: int):
        try:
            return (
                _service().delete_matching_policy(
                    workspace_id=_workspace_id(),
                    matching_policy_id=matching_policy_id,
                    actor_user_id=_actor_user_id(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/matching-policies/<int:matching_policy_id>/versions")
@flowforge_ns.param("matching_policy_id", "Matching policy id whose versions should be listed or extended.")
class FlowForgeMatchingPolicyVersionList(Resource):
    @flowforge_ns.doc(
        summary="List FlowForge matching policy versions",
        description=(
            "Returns saved versions for a matching policy, newest first. Each version includes the deterministic "
            "policy JSON and validation result captured at save time. Raw simulation data is not included here."
        ),
        responses={
            200: "Matching policy versions returned.",
            401: "Authentication required.",
            403: "FlowForge feature or role access required.",
            404: "Matching policy not found.",
        },
    )
    @flowforge_ns.marshal_list_with(models["matching_policy_version"])
    @token_required
    @require_access("flowforge", role="designer")
    def get(self, matching_policy_id: int):
        try:
            return (
                _service().list_matching_policy_versions(
                    workspace_id=_workspace_id(),
                    matching_policy_id=matching_policy_id,
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @flowforge_ns.doc(
        summary="Create a FlowForge matching policy draft version",
        description=(
            "Validates and saves a new draft version for a matching policy. Version numbers are assigned "
            "monotonically by the service. This endpoint does not publish or activate the policy for runtime "
            "execution; publish/runtime wiring is a later phase."
        ),
        responses={
            201: "Matching policy draft version created.",
            400: "Invalid matching policy JSON.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
            404: "Matching policy not found.",
        },
    )
    @flowforge_ns.marshal_with(models["matching_policy_version"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self, matching_policy_id: int):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().create_matching_policy_version(
                    workspace_id=_workspace_id(),
                    matching_policy_id=matching_policy_id,
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                201,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/matching-policies/<int:matching_policy_id>/versions/<int:matching_policy_version_id>")
@flowforge_ns.param("matching_policy_id", "Matching policy id that owns the version.")
@flowforge_ns.param("matching_policy_version_id", "Matching policy version id to delete.")
class FlowForgeMatchingPolicyVersionDetail(Resource):
    @flowforge_ns.doc(
        summary="Delete a FlowForge matching policy version",
        description=(
            "Soft-deletes a saved matching policy version by marking it deleted and hiding it from the normal "
            "version list. Draft and non-published versions may be deleted. Published versions are protected "
            "because workflow runtime nodes may reference them for auditable matching behavior."
        ),
        responses={
            200: "Matching policy version deleted.",
            400: "Published versions cannot be deleted.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
            404: "Matching policy or version not found.",
        },
    )
    @token_required
    @require_access("flowforge", role="designer")
    def delete(self, matching_policy_id: int, matching_policy_version_id: int):
        try:
            return (
                _service().delete_matching_policy_version(
                    workspace_id=_workspace_id(),
                    matching_policy_id=matching_policy_id,
                    matching_policy_version_id=matching_policy_version_id,
                    actor_user_id=_actor_user_id(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/matching-policies/<int:matching_policy_id>/llm-drafts")
@flowforge_ns.param("matching_policy_id", "Matching policy id whose LLM-assisted drafts should be listed or generated.")
class FlowForgeMatchingPolicyLLMDraftList(Resource):
    @flowforge_ns.doc(
        summary="List FlowForge matching policy LLM drafts",
        description=(
            "Returns stored plain-language matching policy draft attempts for a policy. Drafts include the "
            "admin prompt, generated deterministic policy JSON, validation result, model/generator metadata, "
            "and review status. This endpoint is restricted to FlowForge admins because prompts may contain "
            "customer operational details."
        ),
        responses={
            200: "Matching policy LLM drafts returned.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
            404: "Matching policy not found.",
        },
    )
    @flowforge_ns.marshal_list_with(models["matching_policy_llm_draft"])
    @token_required
    @require_access("flowforge", role="designer")
    def get(self, matching_policy_id: int):
        try:
            return (
                _service().list_matching_policy_llm_drafts(
                    workspace_id=_workspace_id(),
                    matching_policy_id=matching_policy_id,
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @flowforge_ns.doc(
        summary="Generate and store a FlowForge matching policy LLM draft",
        description=(
            "Creates an auditable draft from plain-language routing instructions. The generated policy is "
            "validated and stored with validation metadata but is not automatically accepted, published, or "
            "used by runtime execution. The current implementation supports a deterministic local generator "
            "for tests/offline Docker setups and can call an injected/configured LLM path when enabled by the "
            "service layer."
        ),
        responses={
            201: "Matching policy LLM draft generated and stored.",
            400: "Invalid draft request.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
            404: "Matching policy not found.",
        },
    )
    @flowforge_ns.marshal_with(models["matching_policy_llm_draft"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self, matching_policy_id: int):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().create_matching_policy_llm_draft(
                    workspace_id=_workspace_id(),
                    matching_policy_id=matching_policy_id,
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                201,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/matching-policies/<int:matching_policy_id>/llm-drafts/<int:draft_id>/accept")
@flowforge_ns.param("matching_policy_id", "Matching policy id whose LLM draft should be accepted.")
@flowforge_ns.param("draft_id", "LLM draft id to accept as a normal draft matching policy version.")
class FlowForgeMatchingPolicyLLMDraftAcceptance(Resource):
    @flowforge_ns.doc(
        summary="Accept a FlowForge matching policy LLM draft",
        description=(
            "Validates a stored LLM-assisted draft again, creates a normal draft matching-policy version from "
            "the generated policy JSON, and marks the LLM draft as accepted with reviewer metadata. This keeps "
            "LLM output out of runtime until an admin explicitly accepts it."
        ),
        responses={
            201: "LLM draft accepted and matching policy version created.",
            400: "Draft is invalid or cannot be accepted.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
            404: "Matching policy or draft not found.",
        },
    )
    @flowforge_ns.marshal_with(models["matching_policy_llm_draft_acceptance"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self, matching_policy_id: int, draft_id: int):
        try:
            return (
                _service().accept_matching_policy_llm_draft(
                    workspace_id=_workspace_id(),
                    matching_policy_id=matching_policy_id,
                    draft_id=draft_id,
                    actor_user_id=_actor_user_id(),
                ),
                201,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/matching-policies/simulate")
class FlowForgeMatchingPolicySimulation(Resource):
    @flowforge_ns.doc(
        summary="Simulate a FlowForge matching policy draft",
        description=(
            "Runs deterministic matching policy simulation against inline resource records and intake/context "
            "data. This is the first backend foundation for the Matching Policies testing panel. The endpoint "
            "returns eligible, excluded, ranked, and selected candidates with explanations and no-match reason "
            "when no candidate qualifies."
        ),
        responses={
            200: "Policy simulation completed.",
            400: "Invalid simulation request.",
            401: "Authentication required.",
            403: "FlowForge admin access required.",
        },
    )
    @flowforge_ns.marshal_with(models["matching_simulation"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().simulate_matching_policy(
                    workspace_id=_workspace_id(),
                    payload=payload if isinstance(payload, dict) else {},
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
