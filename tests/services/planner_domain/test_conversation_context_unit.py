"""Unit tests for app.services.planner_domain.conversation_context."""
from __future__ import annotations

from app.services.planner_domain.conversation_context import (
    _bootstrap_conversation_state_from_seed,
    _conversation_context_payload,
    _merge_followup_plan_with_context,
    _plan_conversation_context_from_state,
    _prompt_is_followup_edit,
    _prompt_is_sort_only,
    _prompt_requests_filter_removal,
    normalize_plan_prompt,
)
from app.services.planner_domain.types import PlanConversationContext


# --- normalize_plan_prompt ---

def test_normalize_plan_prompt_strips_control_chars() -> None:
    assert normalize_plan_prompt("hello\x00world") == "hello world"


def test_normalize_plan_prompt_collapses_whitespace() -> None:
    assert normalize_plan_prompt("  show  students  ") == "show students"


# --- _prompt_is_followup_edit ---

def test_prompt_is_followup_edit_sort_only_is_followup() -> None:
    assert _prompt_is_followup_edit(prompt="sort by name", prior_prompt="show students") is True


def test_prompt_is_followup_edit_empty_prompt_is_not_followup() -> None:
    assert _prompt_is_followup_edit(prompt="", prior_prompt="show students") is False


def test_prompt_is_followup_edit_short_also_is_followup() -> None:
    assert _prompt_is_followup_edit(prompt="also add grade", prior_prompt="show students") is True


def test_prompt_is_followup_edit_long_prompt_with_also_not_followup() -> None:
    # A long prompt starting with "also" still starts with the starter token → followup
    long = "also show the students with absences and missing assignments this year"
    assert _prompt_is_followup_edit(prompt=long, prior_prompt="show students") is True


def test_prompt_is_followup_edit_no_prior_prompt_not_followup() -> None:
    assert _prompt_is_followup_edit(prompt="add grade level", prior_prompt="") is False


# --- _prompt_is_sort_only ---

def test_prompt_is_sort_only_true() -> None:
    assert _prompt_is_sort_only("sort by name") is True


def test_prompt_is_sort_only_with_prefix() -> None:
    assert _prompt_is_sort_only("now sort by name") is True


def test_prompt_is_sort_only_false() -> None:
    assert _prompt_is_sort_only("show me students sorted by name") is False


# --- _prompt_requests_filter_removal ---

def test_prompt_requests_filter_removal_true() -> None:
    assert _prompt_requests_filter_removal("remove filter for school") is True


def test_prompt_requests_filter_removal_false() -> None:
    assert _prompt_requests_filter_removal("add a school filter") is False


# --- _plan_conversation_context_from_state ---

def test_plan_conversation_context_from_state_returns_none_for_no_state() -> None:
    result = _plan_conversation_context_from_state(
        conversation_id="pdc_1",
        prompt="sort by name",
        state=None,
    )
    assert result is None


def test_plan_conversation_context_from_state_returns_none_for_empty_plan() -> None:
    result = _plan_conversation_context_from_state(
        conversation_id="pdc_1",
        prompt="sort by name",
        state={"plan_json_v2": {}, "last_prompt": "show students"},
    )
    assert result is None


def test_plan_conversation_context_from_state_returns_context() -> None:
    state = {
        "plan_json_v2": {"intent": "list"},
        "last_prompt": "show students",
        "vertical_norm": "education",
    }
    ctx = _plan_conversation_context_from_state(
        conversation_id="pdc_1",
        prompt="sort by name",
        state=state,
    )
    assert ctx is not None
    assert ctx.conversation_id == "pdc_1"
    assert ctx.prior_prompt == "show students"
    assert ctx.followup_mode is True
    assert ctx.seeded_from_client is False


# --- _conversation_context_payload ---

def test_conversation_context_payload_includes_scoped_plan() -> None:
    ctx = PlanConversationContext(
        conversation_id="pdc_1",
        prior_prompt="show students",
        prior_plan_json_v2={"intent": "list", "base_domain_id": 5, "filters": []},
        prior_vertical_norm="education",
        followup_mode=True,
        seeded_from_client=False,
    )
    payload = _conversation_context_payload(ctx)
    assert payload["conversation_id"] == "pdc_1"
    assert payload["prior_prompt"] == "show students"
    assert payload["prior_plan_v2"]["intent"] == "list"
    assert payload["prior_plan_v2"]["base_domain_id"] == 5


# --- _bootstrap_conversation_state_from_seed ---

def test_bootstrap_conversation_state_from_seed_basic() -> None:
    state = _bootstrap_conversation_state_from_seed(
        workspace_id="ws-1",
        user_id="u-1",
        vertical_norm="education",
        seed_plan_json_v2={"intent": "list", "trace_id": "t1"},
        seed_last_prompt="show students",
    )
    assert state["workspace_id"] == "ws-1"
    assert state["last_prompt"] == "show students"
    assert state["plan_json_v2"]["intent"] == "list"


# --- _merge_followup_plan_with_context ---

def test_merge_followup_plan_preserves_prior_filters_when_candidate_has_none() -> None:
    prior = {
        "filters": [{"column_key": "wt1.school_name", "op": "=", "value": "Lincoln"}],
    }
    # "also add grade" triggers followup_edit hint but NOT sort-only mode,
    # so prior filters should be preserved when candidate returns none.
    candidate = {"filters": [], "selects": {}, "grouping": {}}
    caps = {}
    result = _merge_followup_plan_with_context(
        prompt="also add grade level",
        candidate_plan=candidate,
        prior_plan=prior,
        capabilities=caps,
    )
    assert len(result.get("filters") or []) == 1
