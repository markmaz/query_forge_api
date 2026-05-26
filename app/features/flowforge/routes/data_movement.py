from __future__ import annotations

from flask import request
from flask_restx import Resource

from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.features.flowforge.routes.common import _actor_user_id, _int_query_arg, _service, _workspace_id, flowforge_ns, models


def _json_payload() -> dict:
    payload = request.get_json(silent=True) or {}
    return payload if isinstance(payload, dict) else {}


@flowforge_ns.route("/data-sources")
class FlowForgeDataSourceList(Resource):
    @flowforge_ns.doc(summary="List FlowForge data sources")
    @flowforge_ns.marshal_list_with(models["data_source"])
    @token_required
    @require_access("flowforge", role="viewer")
    def get(self):
        try:
            return _service().list_data_sources(workspace_id=_workspace_id()), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @flowforge_ns.doc(summary="Create or update a FlowForge data source")
    @flowforge_ns.expect(models["data_source_upsert"], validate=False)
    @flowforge_ns.marshal_with(models["data_source"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self):
        try:
            return (
                _service().upsert_data_source(
                    workspace_id=_workspace_id(),
                    payload=_json_payload(),
                    actor_user_id=_actor_user_id(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/data-sources/<string:source_key>")
@flowforge_ns.param("source_key", "Workspace-local data source key.")
class FlowForgeDataSourceDetail(Resource):
    @flowforge_ns.doc(summary="Enable or disable a FlowForge data source")
    @flowforge_ns.expect(models["data_movement_enabled_update"], validate=False)
    @flowforge_ns.marshal_with(models["data_source"])
    @token_required
    @require_access("flowforge", role="designer")
    def patch(self, source_key: str):
        try:
            return (
                _service().set_data_source_enabled(
                    workspace_id=_workspace_id(),
                    source_key=source_key,
                    enabled=bool(_json_payload().get("enabled")),
                    actor_user_id=_actor_user_id(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/data-sources/<string:source_key>/test")
@flowforge_ns.param("source_key", "Workspace-local data source key.")
class FlowForgeDataSourceTest(Resource):
    @flowforge_ns.doc(summary="Validate a FlowForge data source configuration")
    @flowforge_ns.marshal_with(models["data_movement_connection_test"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self, source_key: str):
        try:
            return _service().test_data_source(workspace_id=_workspace_id(), source_key=source_key), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/data-destinations")
class FlowForgeDataDestinationList(Resource):
    @flowforge_ns.doc(summary="List FlowForge data destinations")
    @flowforge_ns.marshal_list_with(models["data_destination"])
    @token_required
    @require_access("flowforge", role="viewer")
    def get(self):
        try:
            return _service().list_data_destinations(workspace_id=_workspace_id()), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code

    @flowforge_ns.doc(summary="Create or update a FlowForge data destination")
    @flowforge_ns.expect(models["data_destination_upsert"], validate=False)
    @flowforge_ns.marshal_with(models["data_destination"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self):
        try:
            return (
                _service().upsert_data_destination(
                    workspace_id=_workspace_id(),
                    payload=_json_payload(),
                    actor_user_id=_actor_user_id(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/data-destinations/<string:destination_key>")
@flowforge_ns.param("destination_key", "Workspace-local data destination key.")
class FlowForgeDataDestinationDetail(Resource):
    @flowforge_ns.doc(summary="Enable or disable a FlowForge data destination")
    @flowforge_ns.expect(models["data_movement_enabled_update"], validate=False)
    @flowforge_ns.marshal_with(models["data_destination"])
    @token_required
    @require_access("flowforge", role="designer")
    def patch(self, destination_key: str):
        try:
            return (
                _service().set_data_destination_enabled(
                    workspace_id=_workspace_id(),
                    destination_key=destination_key,
                    enabled=bool(_json_payload().get("enabled")),
                    actor_user_id=_actor_user_id(),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/data-destinations/<string:destination_key>/test")
@flowforge_ns.param("destination_key", "Workspace-local data destination key.")
class FlowForgeDataDestinationTest(Resource):
    @flowforge_ns.doc(summary="Validate a FlowForge data destination configuration")
    @flowforge_ns.marshal_with(models["data_movement_connection_test"])
    @token_required
    @require_access("flowforge", role="designer")
    def post(self, destination_key: str):
        try:
            return _service().test_data_destination(workspace_id=_workspace_id(), destination_key=destination_key), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/dataset-artifacts")
class FlowForgeDatasetArtifactList(Resource):
    @flowforge_ns.doc(
        summary="List FlowForge dataset artifacts",
        params={
            "run_id": "Optional workflow run id filter.",
            "limit": "Maximum artifacts to return. Defaults to 100 and is capped by the service.",
            "offset": "Zero-based artifact offset.",
        },
    )
    @flowforge_ns.marshal_with(models["dataset_artifact_list"])
    @token_required
    @require_access("flowforge", role="viewer")
    def get(self):
        try:
            run_id = request.args.get("run_id")
            return (
                _service().list_dataset_artifacts(
                    workspace_id=_workspace_id(),
                    run_id=int(run_id) if run_id else None,
                    limit=_int_query_arg("limit", 100),
                    offset=_int_query_arg("offset", 0),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except ValueError:
            return {"error": "run_id must be an integer."}, 400


@flowforge_ns.route("/dataset-artifacts/<int:artifact_id>")
@flowforge_ns.param("artifact_id", "Dataset artifact id.")
class FlowForgeDatasetArtifactDetail(Resource):
    @flowforge_ns.doc(summary="Get a FlowForge dataset artifact")
    @flowforge_ns.marshal_with(models["dataset_artifact"])
    @token_required
    @require_access("flowforge", role="viewer")
    def get(self, artifact_id: int):
        try:
            return _service().get_dataset_artifact(workspace_id=_workspace_id(), artifact_id=artifact_id), 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code


@flowforge_ns.route("/data-movement-audit")
class FlowForgeDataMovementAuditList(Resource):
    @flowforge_ns.doc(
        summary="List FlowForge data movement audit rows",
        params={
            "run_id": "Optional workflow run id filter.",
            "limit": "Maximum audit rows to return. Defaults to 100 and is capped by the service.",
            "offset": "Zero-based audit offset.",
        },
    )
    @flowforge_ns.marshal_with(models["data_movement_audit_list"])
    @token_required
    @require_access("flowforge", role="viewer")
    def get(self):
        try:
            run_id = request.args.get("run_id")
            return (
                _service().list_data_movement_audit(
                    workspace_id=_workspace_id(),
                    run_id=int(run_id) if run_id else None,
                    limit=_int_query_arg("limit", 100),
                    offset=_int_query_arg("offset", 0),
                ),
                200,
            )
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except ValueError:
            return {"error": "run_id must be an integer."}, 400
