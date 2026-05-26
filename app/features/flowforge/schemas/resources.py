from __future__ import annotations

from flask_restx import fields


def register_resource_models(namespace):
    resource_set = namespace.model(
        "FlowForgeResourceSet",
        {
            "id": fields.Integer(required=True, description="Internal resource set id."),
            "workspace_id": fields.String(required=True, description="Workspace that owns the resource set."),
            "resource_set_key": fields.String(required=True, description="Stable workspace-local resource set key."),
            "display_name": fields.String(required=True, description="Human-readable resource set name."),
            "description": fields.String(required=False, description="Optional resource set description."),
            "source_type": fields.String(required=True, description="Source type: manual_csv, semantic_domain, api, or webhook."),
            "enabled": fields.Boolean(required=True, description="Whether the resource set can be used by matching."),
            "active_snapshot_batch_id": fields.Integer(
                required=False,
                description="Current compiled snapshot batch id, when one has been activated.",
            ),
            "settings": fields.Raw(required=True, description="Resource-set-specific operational settings."),
        },
    )
    resource_record = namespace.model(
        "FlowForgeResourceRecord",
        {
            "id": fields.Integer(required=True, description="Internal compiled resource record id."),
            "workspace_id": fields.String(required=True),
            "resource_set_id": fields.Integer(required=True),
            "snapshot_batch_id": fields.Integer(required=False),
            "source_record_key": fields.String(required=True, description="Stable source record key within the resource set."),
            "display_name": fields.String(required=False),
            "primary_email": fields.String(required=False),
            "primary_phone": fields.String(required=False),
            "status": fields.String(required=False),
            "effective_status": fields.String(required=False),
            "availability_status": fields.String(required=False),
            "capacity_total": fields.Raw(required=False),
            "capacity_used": fields.Raw(required=False),
            "capacity_available": fields.Raw(required=False),
            "current_load": fields.Raw(required=False),
            "service_area": fields.String(required=False),
            "timezone": fields.String(required=False),
            "source_missing": fields.Boolean(required=True),
            "tags": fields.Raw(required=True),
            "attributes": fields.Raw(required=True),
            "normalized_profile": fields.Raw(required=True),
            "validation_status": fields.String(required=False),
            "validation_errors": fields.Raw(required=True),
        },
    )
    resource_record_update = namespace.model(
        "FlowForgeResourceRecordUpdate",
        {
            "source_record_key": fields.String(required=False),
            "display_name": fields.String(required=False),
            "primary_email": fields.String(required=False),
            "primary_phone": fields.String(required=False),
            "status": fields.String(required=False),
            "effective_status": fields.String(required=False),
            "availability_status": fields.String(required=False),
            "capacity_total": fields.Raw(required=False),
            "capacity_used": fields.Raw(required=False),
            "capacity_available": fields.Raw(required=False),
            "current_load": fields.Raw(required=False),
            "service_area": fields.String(required=False),
            "timezone": fields.String(required=False),
            "source_missing": fields.Boolean(required=False),
            "tags": fields.Raw(required=False),
            "attributes": fields.Raw(required=False),
            "normalized_profile": fields.Raw(required=False),
            "validation_status": fields.String(required=False),
            "validation_errors": fields.Raw(required=False),
        },
    )
    resource_record_list = namespace.model(
        "FlowForgeResourceRecordList",
        {
            "resource_set_id": fields.Integer(required=True),
            "limit": fields.Integer(required=True),
            "offset": fields.Integer(required=True),
            "records": fields.List(fields.Nested(resource_record), required=True),
        },
    )
    snapshot_batch = namespace.model(
        "FlowForgeResourceSnapshotBatch",
        {
            "id": fields.Integer(required=True),
            "workspace_id": fields.String(required=True),
            "resource_set_id": fields.Integer(required=True),
            "batch_key": fields.String(required=True),
            "source_type": fields.String(required=True),
            "mode": fields.String(required=True),
            "status": fields.String(required=True),
            "record_count": fields.Integer(required=True),
            "valid_count": fields.Integer(required=True),
            "invalid_count": fields.Integer(required=True),
            "summary": fields.Raw(required=True),
            "started_at": fields.Raw(required=False),
            "completed_at": fields.Raw(required=False),
        },
    )
    manual_snapshot_response = namespace.model(
        "FlowForgeManualResourceSnapshotResponse",
        {
            "resource_set_id": fields.Integer(required=True),
            "snapshot_batch_id": fields.Integer(required=True),
            "status": fields.String(required=True),
            "record_count": fields.Integer(required=True),
            "valid_count": fields.Integer(required=True),
            "invalid_count": fields.Integer(required=True),
            "activated": fields.Boolean(required=True),
        },
    )
    return {
        "resource_set": resource_set,
        "resource_record": resource_record,
        "resource_record_update": resource_record_update,
        "resource_record_list": resource_record_list,
        "snapshot_batch": snapshot_batch,
        "manual_snapshot_response": manual_snapshot_response,
    }
