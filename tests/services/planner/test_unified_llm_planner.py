from __future__ import annotations

import json

import app.services.planner_domain.service as planner_domain_service_module
from app.services.planner.unified_llm_planner import build_plan_and_slots
from app.services.planner_domain.llm_planning_service import LLMPlanningService
from app.services.planner_domain.service import PlannerDomainService


class _FakeLLM:
    def __init__(self, traces):
        self._traces = list(traces)
        self.calls = 0

    def chat_json_with_trace(self, **kwargs):
        del kwargs
        idx = self.calls if self.calls < len(self._traces) else len(self._traces) - 1
        self.calls += 1
        return dict(self._traces[idx])


class _FakeCapabilitiesService:
    def get_domain_capabilities(self, *, workspace_id, user_id, domain_id, vertical_norm):
        del workspace_id, user_id, vertical_norm
        assert domain_id == 6
        return {
            "domain_id": 6,
            "domain_version": 1,
            "dimensions": [
                {
                    "column_key": "wt20.county_fips_code",
                    "column_name": "county_fips_code",
                    "filterable": True,
                    "workspace_table_id": 20,
                    "model_column_id": 286,
                    "label": "County",
                }
            ],
            "time_columns": [],
            "domain_metrics": [],
            "user_metrics": [],
            "overlay_metrics": [],
        }


class _FakeDomainVectorService:
    def search_domains(self, **kwargs):
        del kwargs
        return {"results": [{"domain_id": 6, "name": "Enrollment", "score": 0.91}]}


def _valid_unified_payload():
    return {
        "slot_hints": {"intent": "list", "entity": "students", "constraints": [], "time_phrases": []},
        "plan_json_v2": {
            "schema_version": 2,
            "intent": "list",
            "selects": {"dimensions": [{"column_key": "wt20.county_fips_code"}], "metrics": []},
            "filters": [],
            "time": {},
            "grouping": {"group_by": ["wt20.county_fips_code"], "order_by": [], "limit": 200},
        },
    }


def test_unified_planner_valid_json_returns_slot_hints_and_plan():
    payload = _valid_unified_payload()
    raw = json.dumps(payload)
    fake_llm = _FakeLLM(
        [
            {
                "parsed": payload,
                "content": raw,
                "raw_text": json.dumps({"model": "qwen2.5-14b", "usage": {"prompt_tokens": 100, "completion_tokens": 80}}),
            }
        ]
    )
    out = build_plan_and_slots(
        prompt="Show students by county",
        normalized_prompt="Show students by county",
        workspace_id="ws-1",
        vertical_norm="education",
        base_domain_id=6,
        domain_name="Enrollment",
        capabilities_compact={"dimensions": [{"column_key": "wt20.county_fips_code"}], "filter_columns": []},
        conversation_context={},
        trace_id="trace-1",
        llm_client=fake_llm,
        max_tokens=256,
    )
    assert out["slot_hints"]["intent"] == "list"
    assert out["plan_json_v2"]["schema_version"] == 2
    assert out["llm_model"] == "qwen2.5-14b"
    assert out["llm_tokens"]["prompt_tokens"] == 100


def test_unified_planner_extracts_json_wrapped_in_text():
    payload = _valid_unified_payload()
    wrapped = f"Here is your result:\n{json.dumps(payload)}\nThanks."
    fake_llm = _FakeLLM([{"parsed": None, "content": wrapped, "raw_text": wrapped}])
    out = build_plan_and_slots(
        prompt="Show students by county",
        normalized_prompt="Show students by county",
        workspace_id="ws-1",
        vertical_norm="education",
        base_domain_id=6,
        domain_name="Enrollment",
        capabilities_compact={"dimensions": [{"column_key": "wt20.county_fips_code"}], "filter_columns": []},
        conversation_context={},
        trace_id="trace-2",
        llm_client=fake_llm,
        max_tokens=256,
    )
    assert out["plan_json_v2"]["intent"] == "list"
    assert fake_llm.calls == 1


def test_unified_planner_retries_once_when_first_json_invalid():
    payload = _valid_unified_payload()
    fake_llm = _FakeLLM(
        [
            {"parsed": None, "content": "not-json", "raw_text": "not-json"},
            {"parsed": payload, "content": json.dumps(payload), "raw_text": json.dumps(payload)},
        ]
    )
    out = build_plan_and_slots(
        prompt="Show students by county",
        normalized_prompt="Show students by county",
        workspace_id="ws-1",
        vertical_norm="education",
        base_domain_id=6,
        domain_name="Enrollment",
        capabilities_compact={"dimensions": [{"column_key": "wt20.county_fips_code"}], "filter_columns": []},
        conversation_context={},
        trace_id="trace-3",
        llm_client=fake_llm,
        max_tokens=256,
    )
    assert out["plan_json_v2"]["schema_version"] == 2
    assert out["attempts"] == 2
    assert out["repaired"] is True


def test_unified_pipeline_invalid_columns_are_repaired(monkeypatch):
    monkeypatch.setattr(planner_domain_service_module, "PLANNER_UNIFIED_LLM", True)
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_ENABLED", False)
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_LLM_EXPLANATION_ENABLED", False)

    def _fake_unified(
        self,
        *,
        prompt,
        normalized_prompt,
        workspace_id,
        vertical_norm,
        base_domain_id,
        domain_name,
        capabilities,
        conversation_context=None,
        trace_id,
        fast_mode=False,
        grounding_bundle=None,
    ):
        del (
            self,
            prompt,
            normalized_prompt,
            workspace_id,
            vertical_norm,
            base_domain_id,
            domain_name,
            capabilities,
            conversation_context,
            trace_id,
            fast_mode,
            grounding_bundle,
        )
        return {
            "slot_hints": {"intent": "list", "entity": "students", "constraints": [], "time_phrases": []},
            "plan_json_v2": {
                "intent": "list",
                "selects": {
                    "dimensions": [{"column_key": "wt20.county_fips_code"}],
                    "metrics": [],
                },
                "filters": [{"column_key": "wt999.not_allowed", "op": "=", "value": "x"}],
                "time": {},
                "grouping": {"group_by": ["wt20.county_fips_code"], "order_by": [], "limit": 200},
            },
            "llm_raw_json": "{}",
            "llm_model": "qwen2.5-14b",
            "llm_tokens": {},
            "attempts": 1,
            "repaired": False,
        }

    monkeypatch.setattr(LLMPlanningService, "_call_llm_unified", _fake_unified)

    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM([{"parsed": {}, "content": "{}", "raw_text": "{}"}]),
    )
    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "base_domain_id": 6,
            "prompt": "show me students by county",
            "debug": True,
        },
        user_id="user-1",
    )
    assert out["validation"]["is_valid"] is True
    assert out["validation"]["repairs_applied"]
    assert any(str(item).startswith("dropped_invalid_filter:") for item in out["validation"]["repairs_applied"])
    selected_keys = [row.get("column_key") for row in out["plan_json_v2"]["selects"]["dimensions"]]
    assert "wt20.county_fips_code" in selected_keys
