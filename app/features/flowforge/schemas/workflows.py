from __future__ import annotations

from flask_restx import fields


def register_workflow_models(namespace):
    workflow_node = namespace.model(
        "FlowForgeWorkflowNode",
        {
            "id": fields.String(required=True, description="Stable node id unique within the workflow graph."),
            "type": fields.String(
                required=True,
                description=(
                    "Node behavior type, for example intake, matching, decision, schedule_trigger, "
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
            "graph": fields.Nested(workflow_graph, required=True),
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
            "created_at": fields.Raw(required=False),
            "published_at": fields.Raw(required=False),
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
        "workflow_ai_draft_request": workflow_ai_draft_request,
        "workflow_ai_draft": workflow_ai_draft,
        "validation_result": validation_result,
        "run_event": run_event,
        "run_inspector": run_inspector,
        "workflow_version": workflow_version,
        "workflow_version_create": workflow_version_create,
    }
