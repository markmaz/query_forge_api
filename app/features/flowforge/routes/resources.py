from __future__ import annotations

from flask import request
from flask_restx import Resource

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.features.flowforge.routes.common import _actor_user_id, _int_query_arg, _service, _workspace_id, flowforge_ns, models


@flowforge_ns.route("/resource-sets")
class FlowForgeResourceSetList(Resource):
    @flowforge_ns.doc(
        summary="List FlowForge resource sets",
        description=(
            "Returns vertical-neutral resource sets available to the current workspace. Resource sets are the "
            "compiled operational resource pools used by FlowForge matching policies. The response includes "
            "source type, enabled state, active snapshot batch, and safe operational settings, but not sensitive "
            "source payloads."
        ),
        responses={
            200: "Resource sets returned.",
            400: "Missing workspace context.",
            401: "Authentication required.",
            403: "FlowForge feature or role access required.",
        },
    )
    @flowforge_ns.marshal_list_with(models["resource_set"])
    @token_required
    @require_access("flowforge", role="viewer")
    def get(self):
        try:
            return _service().list_resource_sets(workspace_id=_workspace_id()), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @flowforge_ns.doc(
        summary="Create a FlowForge resource set",
        description=(
            "Creates a workspace-scoped, vertical-neutral resource set. The first implementation supports "
            "manual CSV and semantic-domain source types at the model boundary; import/refresh execution is "
            "handled by later endpoints. Creating resource sets is an administrative operation because these "
            "sets are later used by matching policies and workflow execution."
        ),
        responses={
            201: "Resource set created.",
            400: "Invalid resource set payload.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
        },
    )
    @flowforge_ns.expect(
        flowforge_ns.model(
            "FlowForgeResourceSetCreateRequest",
            {
                "resource_set_key": models["resource_set"]["resource_set_key"],
                "display_name": models["resource_set"]["display_name"],
                "description": models["resource_set"]["description"],
                "source_type": models["resource_set"]["source_type"],
                "settings": models["resource_set"]["settings"],
            },
        ),
        validate=False,
    )
    @flowforge_ns.marshal_with(models["resource_set"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().create_resource_set(
                    workspace_id=_workspace_id(),
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                201,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/resource-sets/<int:resource_set_id>")
@flowforge_ns.param("resource_set_id", "Resource set id.")
class FlowForgeResourceSetDetail(Resource):
    @flowforge_ns.doc(
        summary="Update a FlowForge resource set",
        description=(
            "Updates administrative state for a workspace-scoped resource set. This currently supports toggling "
            "enabled state so designers can keep a resource pool for audit and review while preventing it from "
            "being used by matching policies and workflow execution."
        ),
        responses={
            200: "Resource set updated.",
            400: "Invalid resource set payload.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
            404: "Resource set not found.",
        },
    )
    @flowforge_ns.expect(
        flowforge_ns.model(
            "FlowForgeResourceSetUpdateRequest",
            {"enabled": models["resource_set"]["enabled"]},
        ),
        validate=False,
    )
    @flowforge_ns.marshal_with(models["resource_set"])
    @token_required
    @require_access("flowforge", role="designer")
    def patch(self, resource_set_id: int):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().update_resource_set(
                    workspace_id=_workspace_id(),
                    resource_set_id=resource_set_id,
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @flowforge_ns.doc(
        summary="Delete a FlowForge resource set",
        description=(
            "Soft-deletes a workspace-scoped resource set by disabling and archiving the resource set header. "
            "Snapshots and records are retained for auditability, but archived sets are excluded from normal "
            "resource-pool listings and matching lookup paths."
        ),
        responses={
            200: "Resource set deleted.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
            404: "Resource set not found.",
        },
    )
    @token_required
    @require_access("flowforge", role="designer")
    def delete(self, resource_set_id: int):
        try:
            return (
                _service().delete_resource_set(
                    workspace_id=_workspace_id(),
                    resource_set_id=resource_set_id,
                    actor_user_id=_actor_user_id(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/resource-sets/<int:resource_set_id>/records")
@flowforge_ns.param("resource_set_id", "Resource set id whose compiled records should be listed.")
class FlowForgeResourceRecordList(Resource):
    @flowforge_ns.doc(
        summary="List compiled FlowForge resource records",
        description=(
            "Returns compiled resource records for a resource set. These records are vertical-neutral snapshots "
            "used by matching policies. Sensitive profile payloads and raw provider/source payloads are not "
            "returned by this endpoint. Use limit and offset for paging; limit is capped by the service."
        ),
        params={
            "limit": "Maximum records to return. Defaults to 100 and is capped at 500.",
            "offset": "Zero-based record offset. Defaults to 0.",
        },
        responses={
            200: "Resource records returned.",
            401: "Authentication required.",
            403: "FlowForge feature or role access required.",
        },
    )
    @flowforge_ns.marshal_with(models["resource_record_list"])
    @token_required
    @require_access("flowforge", role="viewer")
    def get(self, resource_set_id: int):
        try:
            return (
                _service().list_resource_records(
                    workspace_id=_workspace_id(),
                    resource_set_id=resource_set_id,
                    limit=_int_query_arg("limit", 100),
                    offset=_int_query_arg("offset", 0),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/resource-sets/<int:resource_set_id>/records/<int:record_id>")
@flowforge_ns.param("resource_set_id", "Resource set id whose compiled record should be updated.")
@flowforge_ns.param("record_id", "Compiled resource record id.")
class FlowForgeResourceRecordDetail(Resource):
    @flowforge_ns.doc(
        summary="Update a compiled FlowForge resource record",
        description=(
            "Updates one compiled record in a workspace resource set. The endpoint supports editing standard "
            "routing fields such as name, contact, status, capacity, tags, attributes, and normalized_profile. "
            "Customer-specific columns from CSV uploads are retained and editable in normalized_profile."
        ),
        responses={
            200: "Resource record updated.",
            400: "Invalid resource record payload.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
            404: "Resource record not found.",
        },
    )
    @flowforge_ns.expect(models["resource_record_update"], validate=False)
    @flowforge_ns.marshal_with(models["resource_record"])
    @token_required
    @require_access("flowforge", role="designer")
    def patch(self, resource_set_id: int, record_id: int):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().update_resource_record(
                    workspace_id=_workspace_id(),
                    resource_set_id=resource_set_id,
                    record_id=record_id,
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @flowforge_ns.doc(
        summary="Delete a compiled FlowForge resource record",
        description=(
            "Deletes one compiled record from a workspace resource set. Deleting a record removes it from the "
            "active resource pool immediately; historical snapshot batch metadata remains available for audit."
        ),
        responses={
            200: "Resource record deleted.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
            404: "Resource record not found.",
        },
    )
    @token_required
    @require_access("flowforge", role="designer")
    def delete(self, resource_set_id: int, record_id: int):
        try:
            return (
                _service().delete_resource_record(
                    workspace_id=_workspace_id(),
                    resource_set_id=resource_set_id,
                    record_id=record_id,
                    actor_user_id=_actor_user_id(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/resource-sets/<int:resource_set_id>/snapshot-batches")
@flowforge_ns.param("resource_set_id", "Resource set id whose snapshot batches should be listed.")
class FlowForgeResourceSnapshotBatchList(Resource):
    @flowforge_ns.doc(
        summary="List FlowForge resource snapshot batches",
        description=(
            "Returns recent compiled snapshot batches for a resource set. Snapshot batches represent manual "
            "imports or future semantic-domain refreshes and provide the audit trail for what resource data was "
            "available to matching policies at a point in time."
        ),
        params={"limit": "Maximum batches to return. Defaults to 25 and is capped at 100."},
        responses={
            200: "Snapshot batches returned.",
            401: "Authentication required.",
            403: "FlowForge feature or role access required.",
        },
    )
    @flowforge_ns.marshal_list_with(models["snapshot_batch"])
    @token_required
    @require_access("flowforge", role="viewer")
    def get(self, resource_set_id: int):
        try:
            return (
                _service().list_resource_snapshot_batches(
                    workspace_id=_workspace_id(),
                    resource_set_id=resource_set_id,
                    limit=_int_query_arg("limit", 25),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/resource-sets/<int:resource_set_id>/snapshot-batches/manual")
@flowforge_ns.param("resource_set_id", "Resource set id receiving the manual snapshot.")
class FlowForgeManualResourceSnapshot(Resource):
    @flowforge_ns.doc(
        summary="Create a manual FlowForge resource snapshot",
        description=(
            "Creates a compiled resource snapshot batch from records supplied in the request body. This is the "
            "backend foundation for CSV/manual upload workflows and local testing before semantic-domain refresh "
            "is implemented. The endpoint stores vertical-neutral resource records and can activate the created "
            "batch as the resource set's current snapshot. Sensitive profile JSON is accepted by the service "
            "layer but is not returned by the public resource-record listing endpoint."
        ),
        responses={
            201: "Manual snapshot processed.",
            400: "Invalid snapshot payload.",
            401: "Authentication required.",
            403: "FlowForge designer access required.",
        },
    )
    @flowforge_ns.marshal_with(models["manual_snapshot_response"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self, resource_set_id: int):
        try:
            payload = request.get_json(silent=True) or {}
            return (
                _service().create_manual_resource_snapshot(
                    workspace_id=_workspace_id(),
                    resource_set_id=resource_set_id,
                    payload=payload if isinstance(payload, dict) else {},
                    actor_user_id=_actor_user_id(),
                ),
                201,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
