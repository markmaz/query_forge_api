from __future__ import annotations

from flask_restx import fields


def register_data_movement_models(namespace):
    data_source = namespace.model(
        "FlowForgeDataSource",
        {
            "id": fields.Integer(required=False),
            "workspace_id": fields.String(required=True),
            "source_key": fields.String(required=True),
            "display_name": fields.String(required=True),
            "source_type": fields.String(required=True),
            "enabled": fields.Boolean(required=True),
            "mode": fields.String(required=True),
            "config": fields.Raw(required=True),
            "created_at": fields.Raw(required=False),
            "updated_at": fields.Raw(required=False),
        },
    )
    data_source_upsert = namespace.model(
        "FlowForgeDataSourceUpsert",
        {
            "source_key": fields.String(required=True),
            "display_name": fields.String(required=True),
            "source_type": fields.String(required=True),
            "enabled": fields.Boolean(required=False),
            "mode": fields.String(required=False),
            "config": fields.Raw(required=False),
        },
    )
    data_destination = namespace.model(
        "FlowForgeDataDestination",
        {
            "id": fields.Integer(required=False),
            "workspace_id": fields.String(required=True),
            "destination_key": fields.String(required=True),
            "display_name": fields.String(required=True),
            "destination_type": fields.String(required=True),
            "enabled": fields.Boolean(required=True),
            "mode": fields.String(required=True),
            "config": fields.Raw(required=True),
            "created_at": fields.Raw(required=False),
            "updated_at": fields.Raw(required=False),
        },
    )
    data_destination_upsert = namespace.model(
        "FlowForgeDataDestinationUpsert",
        {
            "destination_key": fields.String(required=True),
            "display_name": fields.String(required=True),
            "destination_type": fields.String(required=True),
            "enabled": fields.Boolean(required=False),
            "mode": fields.String(required=False),
            "config": fields.Raw(required=False),
        },
    )
    enabled_update = namespace.model(
        "FlowForgeDataMovementEnabledUpdate",
        {"enabled": fields.Boolean(required=True)},
    )
    connection_test = namespace.model(
        "FlowForgeDataMovementConnectionTest",
        {
            "ok": fields.Boolean(required=True),
            "key": fields.String(required=True),
            "kind": fields.String(required=True),
            "type": fields.String(required=True),
            "mode": fields.String(required=True),
            "enabled": fields.Boolean(required=True),
            "message": fields.String(required=True),
        },
    )
    dataset_artifact = namespace.model(
        "FlowForgeDatasetArtifact",
        {
            "id": fields.Integer(required=True),
            "workspace_id": fields.String(required=True),
            "run_id": fields.Integer(required=False),
            "node_id": fields.String(required=False),
            "artifact_key": fields.String(required=True),
            "artifact_type": fields.String(required=True),
            "storage_kind": fields.String(required=True),
            "storage_ref": fields.Raw(required=True),
            "schema": fields.Raw(required=True),
            "row_count": fields.Integer(required=False),
            "byte_count": fields.Integer(required=False),
            "checksum": fields.String(required=False),
            "status": fields.String(required=True),
            "expires_at": fields.Raw(required=False),
            "created_at": fields.Raw(required=False),
        },
    )
    dataset_artifact_list = namespace.model(
        "FlowForgeDatasetArtifactList",
        {
            "run_id": fields.Integer(required=False),
            "limit": fields.Integer(required=True),
            "offset": fields.Integer(required=True),
            "artifacts": fields.List(fields.Nested(dataset_artifact), required=True),
        },
    )
    data_movement_audit = namespace.model(
        "FlowForgeDataMovementAudit",
        {
            "id": fields.Integer(required=True),
            "workspace_id": fields.String(required=True),
            "run_id": fields.Integer(required=False),
            "node_id": fields.String(required=False),
            "action_type": fields.String(required=True),
            "status": fields.String(required=True),
            "source_key": fields.String(required=False),
            "destination_key": fields.String(required=False),
            "dataset_artifact_id": fields.Integer(required=False),
            "resource_set_id": fields.Integer(required=False),
            "actor_type": fields.String(required=False),
            "actor_id": fields.String(required=False),
            "request": fields.Raw(required=True),
            "result": fields.Raw(required=True),
            "error_message": fields.String(required=False),
            "idempotency_key": fields.String(required=False),
            "started_at": fields.Raw(required=False),
            "completed_at": fields.Raw(required=False),
        },
    )
    data_movement_audit_list = namespace.model(
        "FlowForgeDataMovementAuditList",
        {
            "run_id": fields.Integer(required=False),
            "limit": fields.Integer(required=True),
            "offset": fields.Integer(required=True),
            "audit": fields.List(fields.Nested(data_movement_audit), required=True),
        },
    )
    return {
        "data_source": data_source,
        "data_source_upsert": data_source_upsert,
        "data_destination": data_destination,
        "data_destination_upsert": data_destination_upsert,
        "data_movement_enabled_update": enabled_update,
        "data_movement_connection_test": connection_test,
        "dataset_artifact": dataset_artifact,
        "dataset_artifact_list": dataset_artifact_list,
        "data_movement_audit": data_movement_audit,
        "data_movement_audit_list": data_movement_audit_list,
    }
