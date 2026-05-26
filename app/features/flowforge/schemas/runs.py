from __future__ import annotations

from flask_restx import fields


def register_run_models(namespace):
    run = namespace.model(
        "FlowForgeRun",
        {
            "id": fields.Integer(required=True, description="Internal workflow run id."),
            "workspace_id": fields.String(required=True, description="Workspace that owns the run."),
            "workflow_definition_id": fields.Integer(required=True, description="Workflow definition id used by the run."),
            "workflow_version_id": fields.Integer(required=True, description="Immutable workflow version id used by the run."),
            "intake_event_id": fields.Integer(required=False, description="Source intake event id when run started from an integration."),
            "mode": fields.String(required=True, description="production or test."),
            "run_as_principal_type": fields.String(required=False, description="Run-as principal type used by this run."),
            "run_as_principal_id": fields.String(required=False, description="Run-as principal id used by this run."),
            "run_as_principal_display_name": fields.String(required=False, description="Human-readable run-as principal name when available."),
            "triggered_by_user_id": fields.String(required=False, description="User id that manually triggered this run when applicable."),
            "triggered_by_display_name": fields.String(required=False, description="Human-readable triggering user name when available."),
            "status": fields.String(required=True, description="Current durable run status."),
            "current_node_id": fields.String(required=False, description="Current node id when execution has advanced."),
            "idempotency_key": fields.String(required=True, description="Stable idempotency key used to create the run."),
            "run_context": fields.Raw(required=True, description="Redacted run context stored for runtime/audit inspection."),
            "started_at": fields.Raw(required=False, description="Run start timestamp."),
            "completed_at": fields.Raw(required=False, description="Completion timestamp when finished."),
            "failed_at": fields.Raw(required=False, description="Failure timestamp when failed."),
            "created_at": fields.Raw(required=False, description="Run row creation timestamp."),
            "updated_at": fields.Raw(required=False, description="Run row last update timestamp."),
        },
    )
    run_list = namespace.model(
        "FlowForgeRunList",
        {
            "workspace_id": fields.String(required=True),
            "status": fields.String(required=False),
            "mode": fields.String(required=False),
            "limit": fields.Integer(required=True),
            "offset": fields.Integer(required=True),
            "runs": fields.List(fields.Nested(run), required=True),
        },
    )
    run_event = namespace.model(
        "FlowForgePersistedRunEvent",
        {
            "id": fields.Integer(required=True, description="Internal run-event id."),
            "workspace_id": fields.String(required=True),
            "run_id": fields.Integer(required=True),
            "event_type": fields.String(required=True),
            "node_id": fields.String(required=False),
            "message": fields.String(required=False),
            "event_payload": fields.Raw(required=True, description="Redacted event payload."),
            "actor_type": fields.String(required=False),
            "actor_id": fields.String(required=False),
            "created_at": fields.Raw(required=False),
        },
    )
    run_event_list = namespace.model(
        "FlowForgeRunEventList",
        {
            "workspace_id": fields.String(required=True),
            "run_id": fields.Integer(required=True),
            "limit": fields.Integer(required=True),
            "events": fields.List(fields.Nested(run_event), required=True),
        },
    )
    run_note_request = namespace.model(
        "FlowForgeRunNoteCreateRequest",
        {
            "note": fields.String(required=True, description="Operator note text. Maximum 4000 characters."),
            "idempotency_key": fields.String(
                required=False,
                description="Optional client-supplied key to deduplicate accidental resubmissions.",
            ),
        },
    )
    human_task = namespace.model(
        "FlowForgeHumanTask",
        {
            "id": fields.Integer(required=True, description="Internal human task id."),
            "workspace_id": fields.String(required=True, description="Workspace that owns the task."),
            "run_id": fields.Integer(required=True, description="Workflow run id that owns the task."),
            "task_type": fields.String(required=True, description="Task type such as offer, review, or needs_attention."),
            "resource_set_id": fields.Integer(required=False, description="Resource set involved in the task."),
            "source_record_key": fields.String(required=False, description="Source record key for the candidate/resource."),
            "status": fields.String(required=True, description="Task status such as pending, accepted, declined, or canceled."),
            "assigned_to_principal_type": fields.String(required=False, description="Assignee principal type."),
            "assigned_to_principal_id": fields.String(required=False, description="Assignee principal id."),
            "due_at": fields.Raw(required=False, description="Task due timestamp."),
            "completed_at": fields.Raw(required=False, description="Task completion timestamp."),
            "response": fields.Raw(required=True, description="Redacted response/action metadata."),
            "created_at": fields.Raw(required=False, description="Task creation timestamp."),
            "updated_at": fields.Raw(required=False, description="Task last update timestamp."),
        },
    )
    human_task_list = namespace.model(
        "FlowForgeHumanTaskList",
        {
            "workspace_id": fields.String(required=True),
            "run_id": fields.Integer(required=True),
            "limit": fields.Integer(required=True),
            "tasks": fields.List(fields.Nested(human_task), required=True),
        },
    )
    human_task_queue = namespace.model(
        "FlowForgeHumanTaskQueue",
        {
            "workspace_id": fields.String(required=True),
            "task_type": fields.String(required=False),
            "status": fields.String(required=False),
            "limit": fields.Integer(required=True),
            "offset": fields.Integer(required=True),
            "tasks": fields.List(fields.Nested(human_task), required=True),
        },
    )
    signed_action_create_request = namespace.model(
        "FlowForgeSignedActionCreateRequest",
        {
            "allowed_actions": fields.List(
                fields.String,
                required=True,
                description="Allowed public actions. Phase 7B supports accept and decline.",
            ),
            "expires_at": fields.String(required=True, description="Expiration timestamp for the public action token."),
            "idempotency_key": fields.String(required=False, description="Optional event idempotency key."),
        },
    )
    signed_action_create_response = namespace.model(
        "FlowForgeSignedActionCreateResponse",
        {
            "human_task_id": fields.Integer(required=True),
            "token": fields.String(required=True, description="Plaintext token returned once. Only the hash is stored."),
            "allowed_actions": fields.List(fields.String, required=True),
            "expires_at": fields.Raw(required=True),
        },
    )
    approval_decision_request = namespace.model(
        "FlowForgeApprovalDecisionRequest",
        {
            "decision_note": fields.String(
                required=False,
                description="Optional operator note explaining the approval decision.",
            ),
            "decline_reason": fields.String(
                required=False,
                description="Optional reason when declining an approval task.",
            ),
            "idempotency_key": fields.String(
                required=False,
                description="Optional client-supplied key to deduplicate the decision event.",
            ),
        },
    )
    approval_decision_response = namespace.model(
        "FlowForgeApprovalDecisionResponse",
        {
            "human_task_id": fields.Integer(required=True),
            "run_id": fields.Integer(required=True),
            "action": fields.String(required=True),
            "status": fields.String(required=True),
            "runtime": fields.Raw(required=True),
        },
    )
    public_signed_action_task = namespace.model(
        "FlowForgePublicSignedActionTask",
        {
            "task_type": fields.String(required=True),
            "status": fields.String(required=True),
            "source_record_key": fields.String(required=False),
        },
    )
    public_signed_action = namespace.model(
        "FlowForgePublicSignedAction",
        {
            "valid": fields.Boolean(required=True),
            "allowed_actions": fields.List(fields.String, required=True),
            "expires_at": fields.Raw(required=True),
            "task": fields.Nested(public_signed_action_task, required=True),
        },
    )
    public_signed_action_result = namespace.model(
        "FlowForgePublicSignedActionResult",
        {
            "accepted": fields.Boolean(required=True),
            "action": fields.String(required=True),
            "task": fields.Nested(public_signed_action_task, required=True),
        },
    )
    notification = namespace.model(
        "FlowForgeNotification",
        {
            "id": fields.Integer(required=True),
            "workspace_id": fields.String(required=True),
            "run_id": fields.Integer(required=False),
            "human_task_id": fields.Integer(required=False),
            "channel": fields.String(required=True),
            "recipient": fields.String(required=True),
            "template_key": fields.String(required=True),
            "status": fields.String(required=True),
            "payload_summary": fields.Raw(required=True),
            "provider_message_id": fields.String(required=False),
            "error_message": fields.String(required=False),
            "created_at": fields.Raw(required=False),
            "sent_at": fields.Raw(required=False),
            "failed_at": fields.Raw(required=False),
        },
    )
    notification_list = namespace.model(
        "FlowForgeNotificationList",
        {
            "workspace_id": fields.String(required=True),
            "run_id": fields.Integer(required=True),
            "limit": fields.Integer(required=True),
            "notifications": fields.List(fields.Nested(notification), required=True),
        },
    )
    no_match_escalation_request = namespace.model(
        "FlowForgeNoMatchEscalationRequest",
        {
            "reason": fields.String(required=True, description="Redacted no-match reason."),
            "recipients": fields.List(fields.String, required=False, description="Optional email recipients."),
            "idempotency_key": fields.String(required=False),
        },
    )
    no_match_escalation_response = namespace.model(
        "FlowForgeNoMatchEscalationResponse",
        {
            "run_id": fields.Integer(required=True),
            "status": fields.String(required=True),
            "reason": fields.String(required=True),
            "recipients": fields.List(fields.String, required=True),
            "notification_count": fields.Integer(required=True),
        },
    )
    return {
        "run": run,
        "run_list": run_list,
        "run_event": run_event,
        "run_event_list": run_event_list,
        "run_note_request": run_note_request,
        "human_task": human_task,
        "human_task_list": human_task_list,
        "human_task_queue": human_task_queue,
        "signed_action_create_request": signed_action_create_request,
        "signed_action_create_response": signed_action_create_response,
        "approval_decision_request": approval_decision_request,
        "approval_decision_response": approval_decision_response,
        "public_signed_action": public_signed_action,
        "public_signed_action_result": public_signed_action_result,
        "notification_list": notification_list,
        "no_match_escalation_request": no_match_escalation_request,
        "no_match_escalation_response": no_match_escalation_response,
    }
