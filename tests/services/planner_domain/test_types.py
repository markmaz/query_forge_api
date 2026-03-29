"""Unit tests for app.services.planner_domain.types."""
from __future__ import annotations

from app.services.planner_domain.types import (
    LLMPlanResult,
    PlanConversationContext,
    PlanDomainNextActionsRequest,
    PlanDomainRequest,
    SlotExtractionResult,
)


def test_llm_plan_result_is_frozen() -> None:
    result = LLMPlanResult(
        plan_json={"intent": "list"},
        raw_content='{"intent":"list"}',
        attempts=1,
        repaired=False,
    )
    assert result.plan_json == {"intent": "list"}
    assert result.attempts == 1
    assert result.repaired is False


def test_slot_extraction_result_is_frozen() -> None:
    result = SlotExtractionResult(
        payload={"entity": "student"},
        raw_content='{"entity":"student"}',
        attempts=2,
        repaired=True,
    )
    assert result.payload == {"entity": "student"}
    assert result.repaired is True


def test_plan_conversation_context_is_frozen() -> None:
    ctx = PlanConversationContext(
        conversation_id="pdc_123",
        prior_prompt="show me students",
        prior_plan_json_v2={"intent": "list"},
        prior_vertical_norm="education",
        followup_mode=True,
        seeded_from_client=False,
    )
    assert ctx.conversation_id == "pdc_123"
    assert ctx.followup_mode is True
    assert ctx.seeded_from_client is False


def test_plan_domain_request_validates_conversation_id_strip() -> None:
    req = PlanDomainRequest(
        workspace_id="ws-1",
        prompt="show students",
        conversation_id="  pdc_abc  ",
    )
    assert req.conversation_id == "pdc_abc"


def test_plan_domain_request_empty_conversation_id_becomes_none() -> None:
    req = PlanDomainRequest(
        workspace_id="ws-1",
        prompt="show students",
        conversation_id="   ",
    )
    assert req.conversation_id is None


def test_plan_domain_next_actions_request_validates_conversation_id() -> None:
    req = PlanDomainNextActionsRequest(
        workspace_id="ws-1",
        prompt="show students",
        plan_json_v2={"intent": "list"},
        conversation_id="  pdc_x  ",
    )
    assert req.conversation_id == "pdc_x"
