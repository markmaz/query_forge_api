from __future__ import annotations

from app.features.flowforge.models import WorkflowDefinition

THERAPIST_ROUTING_WORKFLOW: WorkflowDefinition = {
    "id": "therapist-routing",
    "name": "Therapist Intake Routing",
    "description": "Starter workflow for matching intake records with eligible therapists and requesting a response.",
    "status": "starter",
    "graph": {
        "nodes": [
            {
                "id": "intake",
                "type": "intake",
                "label": "Patient Intake",
                "position": {"x": 40, "y": 120},
                "data": {"source": "", "event": ""},
            },
            {
                "id": "match",
                "type": "matching",
                "label": "Find Matching Therapist",
                "position": {"x": 360, "y": 90},
                "data": {"matching_policy_id": ""},
            },
            {
                "id": "offer",
                "type": "human_task",
                "label": "Request Response",
                "position": {"x": 860, "y": 330},
                "data": {
                    "timeout_minutes": 120,
                    "task_mode": "sequential",
                    "communication_template_key": "flowforge.human_task",
                },
            },
            {
                "id": "decision",
                "type": "decision",
                "label": "Accepted?",
                "position": {"x": 580, "y": 330},
                "data": {"outcomes": ["accepted", "declined", "timed_out"]},
            },
            {
                "id": "assign",
                "type": "assignment",
                "label": "Assign Patient",
                "position": {"x": 300, "y": 460},
                "data": {"terminal": True, "reporting_event": "patient_assigned"},
            },
            {
                "id": "decline",
                "type": "event_capture",
                "label": "Capture Decline Reason",
                "position": {"x": 580, "y": 560},
                "data": {"captures": ["decline_reason", "response_time", "timeout"]},
            },
            {
                "id": "next",
                "type": "iterator",
                "label": "Next Therapist",
                "position": {"x": 860, "y": 560},
                "data": {"loop_target": "offer", "stop_when": "candidate_pool_exhausted"},
            },
        ],
        "edges": [
            {"id": "intake-match", "source": "intake", "target": "match"},
            {"id": "match-offer", "source": "match", "target": "offer", "label": "Matched", "branch": "matched"},
            {"id": "match-decline", "source": "match", "target": "decline", "label": "No match", "branch": "no_match"},
            {"id": "offer-decision", "source": "offer", "target": "decision"},
            {"id": "decision-assign", "source": "decision", "target": "assign", "label": "Accepted"},
            {"id": "decision-decline", "source": "decision", "target": "decline", "label": "Declined/Timed out"},
            {"id": "decline-next", "source": "decline", "target": "next"},
            {"id": "next-offer", "source": "next", "target": "offer", "label": "Loop"},
        ],
    },
}
