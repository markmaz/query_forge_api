from __future__ import annotations

from datetime import date, datetime

from flask_restx import fields


class _JsonDateTime(fields.Raw):
    def format(self, value):
        if isinstance(value, datetime | date):
            return value.isoformat()
        return value


def register_workflow_models(namespace):
    workflow_node = namespace.model(
        "FlowForgeWorkflowNode",
        {
            "id": fields.String(required=True, description="Stable node id unique within the workflow graph."),
            "type": fields.String(
                required=True,
                description=(
                    "Node behavior type, for example manual_start, intake, matching, decision, schedule_trigger, "
                    "query_extract, export, import, map_transform, approval, or iterator."
                ),
            ),
            "label": fields.String(required=True, description="Human-readable node label displayed on the canvas."),
            "position": fields.Raw(required=True, description="Canvas position object with x/y coordinates."),
            "data": fields.Raw(required=True, description="Node-specific configuration payload."),
        },
    )
    workflow_edge = namespace.model(
        "FlowForgeWorkflowEdge",
        {
            "id": fields.String(required=True, description="Stable edge id unique within the workflow graph."),
            "source": fields.String(required=True, description="Source node id."),
            "target": fields.String(required=True, description="Target node id."),
            "label": fields.String(required=False, description="Optional branch or transition label."),
            "branch": fields.String(required=False, description="Optional runtime branch/outcome key for routed edges."),
            "branches": fields.List(fields.String, required=False, description="Optional runtime branch/outcome keys for routed edges."),
            "condition": fields.String(required=False, description="Optional runtime condition key for routed edges."),
        },
    )
    workflow_graph = namespace.model(
        "FlowForgeWorkflowGraph",
        {
            "nodes": fields.List(fields.Nested(workflow_node), required=True),
            "edges": fields.List(fields.Nested(workflow_edge), required=True),
            "viewport": fields.Raw(required=False, description="Optional React Flow viewport with x, y, and zoom."),
        },
    )
    workflow_definition = namespace.model(
        "FlowForgeWorkflowDefinition",
        {
            "id": fields.String(required=True, description="Stable workflow definition id."),
            "name": fields.String(required=True, description="Workflow display name."),
            "description": fields.String(required=True, description="Workflow purpose summary."),
            "status": fields.String(required=True, description="Definition lifecycle status."),
            "owner_user_id": fields.String(required=False, description="Workflow owner user id."),
            "owner_display_name": fields.String(required=False, description="Human-readable workflow owner name when available."),
            "lifecycle": fields.String(required=False, description="Workflow lifecycle, for example development or production."),
            "run_as_principal": fields.Raw(required=False, description="Principal used when workflow runs are created."),
            "effective_permissions": fields.Raw(required=False, description="Resolved permissions for the current actor."),
            "created_at": _JsonDateTime(required=False, description="Workflow definition creation timestamp."),
            "updated_at": _JsonDateTime(required=False, description="Workflow definition last update timestamp."),
            "graph": fields.Nested(workflow_graph, required=True),
        },
    )
    workflow_permission_entry = namespace.model(
        "FlowForgeWorkflowPermissionEntry",
        {
            "id": fields.Integer(required=False),
            "principal_type": fields.String(required=True, description="Principal type: user, workspace_role, or workspace."),
            "principal_id": fields.String(required=True, description="Principal id."),
            "principal_display_name": fields.String(required=False, description="Human-readable principal name when available."),
            "permission": fields.String(required=True, description="Granted workflow object permission."),
            "granted_by": fields.String(required=False),
            "granted_at": _JsonDateTime(required=False),
        },
    )
    workflow_permissions = namespace.model(
        "FlowForgeWorkflowPermissions",
        {
            "workflow_definition_id": fields.Integer(required=True),
            "items": fields.List(fields.Nested(workflow_permission_entry), required=True),
        },
    )
    workflow_permissions_update = namespace.model(
        "FlowForgeWorkflowPermissionsUpdateRequest",
        {
            "permissions": fields.List(fields.Raw, required=False, description="ACL entries to grant or update."),
            "grants": fields.List(fields.Raw, required=False, description="ACL entries to grant or update."),
            "revocations": fields.List(fields.Raw, required=False, description="ACL principal entries to revoke."),
        },
    )
    workflow_owner_update = namespace.model(
        "FlowForgeWorkflowOwnerUpdateRequest",
        {"owner_user_id": fields.String(required=True, description="New workflow owner user id.")},
    )
    workflow_metadata_update = namespace.model(
        "FlowForgeWorkflowMetadataUpdateRequest",
        {
            "name": fields.String(required=True, description="Workflow display name."),
            "description": fields.String(required=False, description="Workflow purpose summary."),
        },
    )
    workflow_run_as_update = namespace.model(
        "FlowForgeWorkflowRunAsUpdateRequest",
        {
            "principal_type": fields.String(required=True, description="Run-as principal type."),
            "principal_id": fields.String(required=True, description="Run-as principal id."),
        },
    )
    workflow_run_as_principal = namespace.model(
        "FlowForgeWorkflowRunAsPrincipal",
        {
            "principal_type": fields.String(required=True),
            "principal_id": fields.String(required=True),
            "display_name": fields.String(required=True),
            "description": fields.String(required=False),
            "status": fields.String(required=True),
            "production_eligible": fields.Boolean(required=True),
        },
    )
    workflow_run_as_principals = namespace.model(
        "FlowForgeWorkflowRunAsPrincipals",
        {
            "workspace_id": fields.String(required=True),
            "items": fields.List(fields.Nested(workflow_run_as_principal), required=True),
        },
    )
    workflow_manual_run_request = namespace.model(
        "FlowForgeWorkflowManualRunRequest",
        {
            "mode": fields.String(required=False, description="Run mode. Defaults to test."),
            "start_node_id": fields.String(required=False, description="Optional explicit start node id."),
            "input": fields.Raw(required=False, description="Optional manual run input payload."),
            "idempotency_key": fields.String(required=False, description="Optional client idempotency key."),
        },
    )
    workflow_manual_run = namespace.model(
        "FlowForgeWorkflowManualRun",
        {
            "run_id": fields.Integer(required=True),
            "workflow_definition_id": fields.Integer(required=True),
            "workflow_version_id": fields.Integer(required=True),
            "status": fields.String(required=True),
            "mode": fields.String(required=True),
            "current_node_id": fields.String(required=False),
            "idempotency_key": fields.String(required=True),
            "created": fields.Boolean(required=True),
        },
    )
    workflow_readiness_finding = namespace.model(
        "FlowForgeWorkflowReadinessFinding",
        {
            "code": fields.String(required=True),
            "message": fields.String(required=True),
            "severity": fields.String(required=True),
            "node_id": fields.String(required=False),
        },
    )
    workflow_readiness_step = namespace.model(
        "FlowForgeWorkflowReadinessStep",
        {
            "id": fields.String(required=True),
            "label": fields.String(required=True),
            "state": fields.String(required=True, description="complete, current, or blocked."),
            "detail": fields.String(required=True),
        },
    )
    workflow_readiness = namespace.model(
        "FlowForgeWorkflowReadiness",
        {
            "workflow_definition_id": fields.Integer(required=True),
            "status": fields.String(required=True, description="ready, needs_publish, or blocked."),
            "can_publish": fields.Boolean(required=True),
            "can_run": fields.Boolean(required=True),
            "latest_valid_draft_version_id": fields.Integer(required=False),
            "latest_published_version_id": fields.Integer(required=False),
            "latest_run_id": fields.Integer(required=False),
            "latest_run_status": fields.String(required=False),
            "latest_run_mode": fields.String(required=False),
            "blockers": fields.List(fields.Nested(workflow_readiness_finding), required=True),
            "warnings": fields.List(fields.Nested(workflow_readiness_finding), required=True),
            "steps": fields.List(fields.Nested(workflow_readiness_step), required=True),
        },
    )
    workflow_definition_create = namespace.model(
        "FlowForgeWorkflowDefinitionCreateRequest",
        {
            "workflow_key": fields.String(required=True, description="Stable workspace-local workflow key."),
            "name": fields.String(required=True, description="Workflow display name."),
            "description": fields.String(required=False, description="Workflow purpose summary."),
            "graph": fields.Nested(workflow_graph, required=True, description="Initial workflow graph."),
            "settings": fields.Raw(required=False, description="Optional workflow settings JSON."),
        },
    )
    workflow_ai_draft_request = namespace.model(
        "FlowForgeWorkflowAIDraftRequest",
        {
            "prompt": fields.String(required=True, description="Plain-language workflow designer instruction."),
            "graph": fields.Nested(workflow_graph, required=True, description="Current workflow graph to modify."),
            "context": fields.Raw(required=False, description="Optional governed designer context for AI graph drafting."),
            "use_llm": fields.Boolean(required=False, description="Use the workspace FlowForge LLM role when true."),
        },
    )
    validation_result = namespace.model(
        "FlowForgeValidationResult",
        {
            "valid": fields.Boolean(required=True, description="True when the graph has no blocking validation errors."),
            "errors": fields.List(fields.String, required=True, description="Blocking graph validation errors."),
            "warnings": fields.List(fields.String, required=True, description="Non-blocking warnings, including loop detection."),
        },
    )
    workflow_ai_draft = namespace.model(
        "FlowForgeWorkflowAIDraft",
        {
            "prompt": fields.String(required=True),
            "graph": fields.Nested(workflow_graph, required=True),
            "plain_language_summary": fields.String(required=True),
            "validation_status": fields.String(required=True),
            "validation_result": fields.Nested(validation_result, required=True),
            "model_provider": fields.String(required=False),
            "model_name": fields.String(required=False),
            "draft_source": fields.String(required=True),
        },
    )
    run_event = namespace.model(
        "FlowForgeRunEvent",
        {
            "id": fields.String(required=True),
            "event_type": fields.String(required=True),
            "node_id": fields.String(required=False),
            "message": fields.String(required=True),
            "timestamp": fields.String(required=True),
            "data": fields.Raw(required=True),
        },
    )
    run_inspector = namespace.model(
        "FlowForgeRunInspector",
        {
            "workflow_id": fields.String(required=True),
            "mode": fields.String(required=True),
            "status": fields.String(required=True),
            "events": fields.List(fields.Nested(run_event), required=True),
            "notes": fields.List(fields.String, required=True),
        },
    )
    workflow_version = namespace.model(
        "FlowForgeWorkflowVersion",
        {
            "id": fields.Integer(required=True),
            "workspace_id": fields.String(required=True),
            "workflow_definition_id": fields.Integer(required=True),
            "version_number": fields.Integer(required=True),
            "version_status": fields.String(required=True),
            "graph": fields.Raw(required=True),
            "validation_status": fields.String(required=True),
            "validation_result": fields.Raw(required=True),
            "matching_policy_refs": fields.Raw(required=True),
            "settings": fields.Raw(required=True),
            "created_at": _JsonDateTime(required=False),
            "published_at": _JsonDateTime(required=False),
        },
    )
    workflow_version_create = namespace.model(
        "FlowForgeWorkflowVersionCreateRequest",
        {
            "graph": fields.Nested(workflow_graph, required=True, description="Draft graph to validate and persist."),
            "matching_policy_refs": fields.Raw(required=False, description="Optional matching policy references found in nodes."),
            "settings": fields.Raw(required=False, description="Optional version settings JSON."),
        },
    )
    return {
        "workflow_definition": workflow_definition,
        "workflow_definition_create": workflow_definition_create,
        "workflow_permissions": workflow_permissions,
        "workflow_permissions_update": workflow_permissions_update,
        "workflow_owner_update": workflow_owner_update,
        "workflow_metadata_update": workflow_metadata_update,
        "workflow_run_as_update": workflow_run_as_update,
        "workflow_run_as_principals": workflow_run_as_principals,
        "workflow_manual_run_request": workflow_manual_run_request,
        "workflow_manual_run": workflow_manual_run,
        "workflow_readiness": workflow_readiness,
        "workflow_ai_draft_request": workflow_ai_draft_request,
        "workflow_ai_draft": workflow_ai_draft,
        "validation_result": validation_result,
        "run_event": run_event,
        "run_inspector": run_inspector,
        "workflow_version": workflow_version,
        "workflow_version_create": workflow_version_create,
    }
