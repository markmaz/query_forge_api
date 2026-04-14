from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.planner_domain.service import PlannerDomainService


class _MemoryConversationStore:
    def __init__(self) -> None:
        self.rows = {}

    def get_state(self, *, workspace_id: str, user_id: str, conversation_id: str):
        return self.rows.get((workspace_id, user_id, conversation_id))

    def save_state(self, *, workspace_id: str, user_id: str, conversation_id: str, state, qf_ttl_seconds: int):
        del qf_ttl_seconds
        self.rows[(workspace_id, user_id, conversation_id)] = dict(state)


class _CapsService:
    def get_domain_capabilities(self, *, workspace_id, user_id, domain_id):
        del workspace_id, user_id
        assert domain_id == 5
        return {
            "domain_id": 5,
            "domain_version": 1,
            "dimensions": [
                {
                    "column_key": "wt20.school_name",
                    "label": "School Name",
                    "data_type": "string",
                    "filterable": True,
                    "workspace_table_id": 20,
                    "model_column_id": 99,
                    "column_name": "school_name",
                },
                {
                    "column_key": "wt23.first_name",
                    "label": "First Name",
                    "data_type": "string",
                    "filterable": True,
                    "workspace_table_id": 23,
                    "model_column_id": 315,
                    "column_name": "first_name",
                },
                {
                    "column_key": "wt23.last_name",
                    "label": "Last Name",
                    "data_type": "string",
                    "filterable": True,
                    "workspace_table_id": 23,
                    "model_column_id": 316,
                    "column_name": "last_name",
                },
                {
                    "column_key": "wt30.position_title",
                    "label": "Position Title",
                    "data_type": "string",
                    "filterable": True,
                    "workspace_table_id": 30,
                    "model_column_id": 602,
                    "column_name": "position_title",
                },
            ],
            "domain_metrics": [],
            "user_metrics": [],
            "overlay_metrics": [],
            "time_columns": [],
        }


class _DomainVector:
    def search_domains(self, **kwargs):
        del kwargs
        return {"results": [{"domain_id": 5, "name": "Staff & Assignments", "score": 0.9}]}


class _FollowupLLM:
    def __init__(self) -> None:
        self.followup_context_seen = False

    def chat_json_with_trace(self, **kwargs):
        user_prompt = str(kwargs.get("user_prompt") or "")
        prompt_l = user_prompt.lower()

        if "task: extract lightweight planning slots" in prompt_l:
            return {
                "parsed": {
                    "intent": "list",
                    "entity": "staff",
                    "constraints": [],
                    "time_phrases": [],
                },
                "content": "{}",
                "raw_text": "{}",
            }

        if "prompt: sort by position" in prompt_l:
            self.followup_context_seen = "conversation context for follow-up turn" in prompt_l
            return {
                "parsed": {
                    "intent": "list",
                    "selects": {"dimensions": [{"column_key": "wt30.position_title"}], "metrics": []},
                    "filters": [],
                    "time": {},
                    "grouping": {
                        "group_by": ["wt30.position_title"],
                        "order_by": [{"by": "wt30.position_title", "dir": "asc"}],
                        "limit": None,
                    },
                },
                "content": "{}",
                "raw_text": "{}",
            }

        return {
            "parsed": {
                "intent": "list",
                "selects": {
                    "dimensions": [
                        {"column_key": "wt20.school_name"},
                        {"column_key": "wt23.first_name"},
                        {"column_key": "wt23.last_name"},
                        {"column_key": "wt30.position_title"},
                    ],
                    "metrics": [],
                },
                "filters": [{"column_key": "wt20.school_name", "op": "=", "value": "Barksdale Elementary"}],
                "time": {},
                "grouping": {
                    "group_by": ["wt20.school_name", "wt23.first_name", "wt23.last_name", "wt30.position_title"],
                    "order_by": [],
                    "limit": None,
                },
            },
            "content": "{}",
            "raw_text": "{}",
        }


def test_plan_domain_conversation_followup_sort_preserves_prior_context() -> None:
    store = _MemoryConversationStore()
    llm = _FollowupLLM()
    svc = PlannerDomainService(
        capabilities_service=_CapsService(),
        domain_vector_service=_DomainVector(),
        llm_client=llm,
        conversation_store=store,
    )

    first = svc.plan(
        {
            "workspace_id": "ws-1",
            "base_domain_id": 5,
            "prompt": "show me the staff at barksdale elementary",
        },
        user_id="user-1",
    )
    conversation_id = first["conversation_id"]

    second = svc.plan(
        {
            "workspace_id": "ws-1",
            "prompt": "sort by position",
            "conversation_id": conversation_id,
        },
        user_id="user-1",
    )

    assert second["conversation_id"] == conversation_id
    assert any(
        item.get("column_key") == "wt20.school_name" and item.get("value") == "Barksdale Elementary"
        for item in second["plan_json_v2"]["filters"]
    )
    sorting = second["sql_json"].get("sorting") or []
    assert sorting
    assert (sorting[0].get("col") or {}).get("columnName") == "position_title"
    assert llm.followup_context_seen is True


def test_plan_domain_unknown_conversation_id_returns_404() -> None:
    svc = PlannerDomainService(
        capabilities_service=_CapsService(),
        domain_vector_service=_DomainVector(),
        llm_client=_FollowupLLM(),
        conversation_store=_MemoryConversationStore(),
    )

    with pytest.raises(ForgeError) as exc:
        svc.plan(
            {
                "workspace_id": "ws-1",
                "prompt": "sort by position",
                "conversation_id": "pdc_missing",
            },
            user_id="user-1",
        )

    assert exc.value.status_code == 404


def test_plan_domain_unknown_conversation_id_can_resume_from_client_seed() -> None:
    llm = _FollowupLLM()
    svc = PlannerDomainService(
        capabilities_service=_CapsService(),
        domain_vector_service=_DomainVector(),
        llm_client=llm,
        conversation_store=_MemoryConversationStore(),
    )

    seed_plan = {
        "schema_version": 2,
        "trace_id": "trace-seed",
        "workspace_id": "ws-1",
        "base_domain_id": 5,
        "intent": "list",
        "selects": {
            "dimensions": [
                {"column_key": "wt20.school_name"},
                {"column_key": "wt23.first_name"},
                {"column_key": "wt23.last_name"},
                {"column_key": "wt30.position_title"},
            ],
            "metrics": [],
        },
        "filters": [{"column_key": "wt20.school_name", "op": "=", "value": "Barksdale Elementary"}],
        "time": {},
        "grouping": {
            "group_by": ["wt20.school_name", "wt23.first_name", "wt23.last_name", "wt30.position_title"],
            "order_by": [],
            "limit": None,
        },
    }

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "prompt": "sort by position",
            "conversation_id": "pdc_missing",
            "context_seed_plan_json_v2": seed_plan,
            "context_seed_last_prompt": "show me the staff at barksdale elementary",
        },
        user_id="user-1",
    )

    assert out["conversation_id"] == "pdc_missing"
    assert any(
        item.get("column_key") == "wt20.school_name" and item.get("value") == "Barksdale Elementary"
        for item in out["plan_json_v2"]["filters"]
    )
    sorting = out["sql_json"].get("sorting") or []
    assert sorting
    assert (sorting[0].get("col") or {}).get("columnName") == "position_title"
    assert llm.followup_context_seen is True
