from __future__ import annotations

from app.features.flowforge.runtime.notifications import FlowForgeNotificationDispatcher


class _RuntimeRepo:
    def __init__(self) -> None:
        self.notifications = [
            {
                "id": 701,
                "workspace_id": "ws-1",
                "run_id": 90,
                "human_task_id": None,
                "channel": "email",
                "recipient": "ops@example.com",
                "template_key": "flowforge.no_match",
                "status": "pending",
                "payload_summary_json": {"reason": "No eligible resources.", "patient_name": "Jane Patient"},
            }
        ]
        self.sent = []
        self.failed = []
        self.events = []
        self.needs_attention = []

    def list_pending_notifications(self, *, limit: int):
        assert limit == 25
        return list(self.notifications)

    def mark_notification_sent(self, **payload):
        self.sent.append(payload)
        return True

    def mark_notification_failed(self, **payload):
        self.failed.append(payload)
        return True

    def mark_run_needs_attention(self, **payload):
        self.needs_attention.append(payload)
        return True

    def append_run_event(self, **payload):
        self.events.append(payload)
        return len(self.events)


class _TemplateRepo:
    def __init__(self, template: dict | None = None) -> None:
        self.template = template
        self.lookups = []

    def get_active_template_by_key(self, **payload):
        self.lookups.append(payload)
        return self.template


def test_notification_dispatcher_sends_minimal_email_and_marks_sent():
    repo = _RuntimeRepo()
    sent_messages = []

    dispatcher = FlowForgeNotificationDispatcher(
        runtime_repository=repo,
        communication_template_repository=_TemplateRepo(),
        email_sender=lambda recipient, subject, html: sent_messages.append((recipient, subject, html)),
    )

    result = dispatcher.dispatch_pending(limit=25)

    assert result == {"status": "completed", "processed": 1, "sent": 1, "failed": 0}
    assert repo.sent[0]["notification_id"] == 701
    assert repo.sent[0]["provider_message_id"] == "local-email"
    assert repo.events[0]["event_type"] == "workflow.notification.sent"
    assert sent_messages[0][0] == "ops@example.com"
    assert "No eligible resources." in sent_messages[0][2]
    assert "Jane Patient" not in sent_messages[0][2]


def test_notification_dispatcher_marks_failed_when_sender_raises():
    repo = _RuntimeRepo()

    def _raise(*args, **kwargs):
        raise RuntimeError("smtp unavailable")

    dispatcher = FlowForgeNotificationDispatcher(
        runtime_repository=repo,
        communication_template_repository=_TemplateRepo(),
        email_sender=_raise,
    )

    result = dispatcher.dispatch_pending(limit=25)

    assert result == {"status": "completed_with_failures", "processed": 1, "sent": 0, "failed": 1}
    assert repo.failed[0]["notification_id"] == 701
    assert "smtp unavailable" in repo.failed[0]["error_message"]
    assert repo.needs_attention == [{"workspace_id": "ws-1", "run_id": 90}]
    assert repo.events[0]["event_type"] == "workflow.notification.failed"
    assert repo.events[0]["event_payload"]["run_status"] == "needs_attention"


def test_notification_dispatcher_renders_human_task_action_link_without_intake_details():
    repo = _RuntimeRepo()
    repo.notifications[0] = {
        **repo.notifications[0],
        "template_key": "flowforge.human_task",
        "recipient": "therapist@example.com",
        "payload_summary_json": {
            "resource_display_name": "Jane Resource",
            "action_url": "http://localhost:3000/flowforge/actions/ffact_123",
            "action_urls": {
                "open_task": "http://localhost:3000/flowforge/actions/ffact_123",
                "accept": "http://localhost:3000/flowforge/actions/ffact_123?action=accept",
                "decline": "http://localhost:3000/flowforge/actions/ffact_123?action=decline",
            },
            "patient_name": "Jane Patient",
        },
    }
    sent_messages = []
    dispatcher = FlowForgeNotificationDispatcher(
        runtime_repository=repo,
        communication_template_repository=_TemplateRepo(),
        email_sender=lambda recipient, subject, html: sent_messages.append((recipient, subject, html)),
    )

    result = dispatcher.dispatch_pending(limit=25)

    assert result["sent"] == 1
    assert sent_messages[0][0] == "therapist@example.com"
    assert sent_messages[0][1] == "Workflow task"
    assert "FlowForge" not in sent_messages[0][1]
    assert "FlowForge" not in sent_messages[0][2]
    assert "http://localhost:3000/flowforge/actions/ffact_123" in sent_messages[0][2]
    assert "Jane Patient" not in sent_messages[0][2]


def test_notification_dispatcher_renders_active_custom_template():
    repo = _RuntimeRepo()
    repo.notifications[0] = {
        **repo.notifications[0],
        "template_key": "therapist-task",
        "recipient": "therapist@example.com",
        "human_task_id": 301,
        "payload_summary_json": {
            "resource_display_name": "Dr. Lane",
            "source_record_key": "therapist-1",
            "action_url": "http://localhost:3000/flowforge/actions/ffact_123",
            "action_urls": {
                "open_task": "http://localhost:3000/flowforge/actions/ffact_123",
                "accept": "http://localhost:3000/flowforge/actions/ffact_123?action=accept",
                "decline": "http://localhost:3000/flowforge/actions/ffact_123?action=decline",
            },
            "expires_at": "2026-05-06T18:00:00Z",
            "intake": {
                "requested_service": "Anxiety therapy",
                "preferred_days": "Monday, Wednesday",
            },
        },
    }
    template_repo = _TemplateRepo(
        {
            "id": 501,
            "workspace_id": "ws-1",
            "template_key": "therapist-task",
            "channel": "email",
            "purpose": "human_task",
            "subject": "FlowForge task for {{selected_resource.display_name}}",
            "body_blocks_json": [
                {"type": "heading", "content": "FlowForge task for {{selected_resource.display_name}}"},
                {"type": "text", "content": "Please respond by {{task.due_at}} in FlowForge."},
                {"type": "field_list", "fields": ["intake.requested_service", "intake.preferred_days"]},
                {"type": "action_buttons", "actions": ["accept", "decline"]},
            ],
            "status": "active",
            "validation_status": "valid",
        }
    )
    sent_messages = []
    dispatcher = FlowForgeNotificationDispatcher(
        runtime_repository=repo,
        communication_template_repository=template_repo,
        email_sender=lambda recipient, subject, html: sent_messages.append((recipient, subject, html)),
    )

    result = dispatcher.dispatch_pending(limit=25)

    assert result["sent"] == 1
    assert template_repo.lookups[0] == {
        "workspace_id": "ws-1",
        "template_key": "therapist-task",
        "channel": "email",
    }
    assert sent_messages[0][1] == "Workflow task for Dr. Lane"
    assert "Workflow task for Dr. Lane" in sent_messages[0][2]
    assert "in Workflow" in sent_messages[0][2]
    assert "FlowForge" not in sent_messages[0][1]
    assert "FlowForge" not in sent_messages[0][2]
    assert "Anxiety therapy" in sent_messages[0][2]
    assert "Monday, Wednesday" in sent_messages[0][2]
    assert "2026-05-06T18:00:00Z" in sent_messages[0][2]
    assert 'href="http://localhost:3000/flowforge/actions/ffact_123?action=accept"' in sent_messages[0][2]
    assert 'data-flowforge-action="accept"' in sent_messages[0][2]
    assert 'href="http://localhost:3000/flowforge/actions/ffact_123?action=decline"' in sent_messages[0][2]
    assert 'data-flowforge-action="decline"' in sent_messages[0][2]
