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

    def list_pending_notifications(self, *, limit: int):
        assert limit == 25
        return list(self.notifications)

    def mark_notification_sent(self, **payload):
        self.sent.append(payload)
        return True

    def mark_notification_failed(self, **payload):
        self.failed.append(payload)
        return True

    def append_run_event(self, **payload):
        self.events.append(payload)
        return len(self.events)


def test_notification_dispatcher_sends_minimal_email_and_marks_sent():
    repo = _RuntimeRepo()
    sent_messages = []

    dispatcher = FlowForgeNotificationDispatcher(
        runtime_repository=repo,
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

    dispatcher = FlowForgeNotificationDispatcher(runtime_repository=repo, email_sender=_raise)

    result = dispatcher.dispatch_pending(limit=25)

    assert result == {"status": "completed", "processed": 1, "sent": 0, "failed": 1}
    assert repo.failed[0]["notification_id"] == 701
    assert "smtp unavailable" in repo.failed[0]["error_message"]
    assert repo.events[0]["event_type"] == "workflow.notification.failed"


def test_notification_dispatcher_renders_human_task_action_link_without_intake_details():
    repo = _RuntimeRepo()
    repo.notifications[0] = {
        **repo.notifications[0],
        "template_key": "flowforge.human_task",
        "recipient": "therapist@example.com",
        "payload_summary_json": {
            "resource_display_name": "Jane Resource",
            "action_url": "http://localhost:3000/flowforge/actions/ffact_123",
            "patient_name": "Jane Patient",
        },
    }
    sent_messages = []
    dispatcher = FlowForgeNotificationDispatcher(
        runtime_repository=repo,
        email_sender=lambda recipient, subject, html: sent_messages.append((recipient, subject, html)),
    )

    result = dispatcher.dispatch_pending(limit=25)

    assert result["sent"] == 1
    assert sent_messages[0][0] == "therapist@example.com"
    assert "FlowForge workflow task" in sent_messages[0][1]
    assert "http://localhost:3000/flowforge/actions/ffact_123" in sent_messages[0][2]
    assert "Jane Patient" not in sent_messages[0][2]
