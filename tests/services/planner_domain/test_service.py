from __future__ import annotations

from datetime import date
import logging

import pytest
from sqlalchemy.exc import SQLAlchemyError
from valkey.exceptions import ValkeyError

from app.exceptions.forge_error import ForgeError
from app.services.planner.semantic_candidate_models import SemanticCandidatePayload, SemanticConceptCandidate
from app.services.planner.semantic_grounding_service import SemanticGroundingBundle
from app.services.planner_domain import service as planner_domain_service_module
import app.services.planner_domain.pipeline_trace as pipeline_trace_module
import app.services.planner_domain.semantic_integration_service as semantic_integration_module
from app.services.planner_domain.column_scoring import _column_heuristic_boost, _required_column_keys
from app.services.planner_domain.conversation_context import _prompt_is_followup_edit
from app.services.planner_domain.domain_selection_service import DomainSelectionService
from app.services.planner_domain.llm_planning_service import LLMPlanningService
from app.services.planner_domain.normalizers.metric import _normalize_top_bottom_ranking_in_plan
from app.services.planner_domain.normalizers.time import (
    _normalize_relative_time_in_plan,
    _normalize_year_keyword_filters_in_plan,
)
from app.services.planner_domain.plan_helpers import (
    _district_county_retry_hint,
    _serialize_domain_candidates_for_debug,
)
from app.services.planner_domain.service import PlannerDomainService
from app.services.planner_domain.types import LLMPlanResult, SlotExtractionResult


@pytest.fixture(autouse=True)
def _disable_unified_llm(monkeypatch):
    monkeypatch.setattr(planner_domain_service_module, "PLANNER_UNIFIED_LLM", False)


@pytest.fixture(autouse=True)
def _isolate_pipeline_logs(monkeypatch, tmp_path):
    monkeypatch.setattr(
        pipeline_trace_module,
        "QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE",
        str(tmp_path / "plan_domain_pipeline_timing.log"),
    )
    monkeypatch.setattr(
        pipeline_trace_module,
        "QF_PLAN_DOMAIN_PIPELINE_TRACE_LOG_FILE",
        str(tmp_path / "plan_domain_pipeline_trace.jsonl"),
    )

    profile_logger = logging.getLogger(pipeline_trace_module._PROFILE_LOGGER_NAME)
    for handler in list(profile_logger.handlers):
        profile_logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    trace_logger = logging.getLogger(pipeline_trace_module._TRACE_LOGGER_NAME)
    for handler in list(trace_logger.handlers):
        trace_logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    monkeypatch.setattr(pipeline_trace_module, "_PROFILE_LOGGER_INITIALIZED", False)
    monkeypatch.setattr(pipeline_trace_module, "_TRACE_LOGGER_INITIALIZED", False)


class _FakeCapabilitiesService:
    def get_domain_capabilities(self, *, workspace_id, user_id, domain_id):
        del workspace_id, user_id
        assert domain_id == 6
        return {
            "domain_id": 6,
            "domain_version": 3,
            "dimensions": [
                {
                    "column_key": "wt20.county_fips_code",
                    "label": "County",
                    "data_type": "int",
                    "filterable": True,
                    "workspace_table_id": 20,
                    "model_column_id": 286,
                    "column_name": "county_fips_code",
                }
            ],
            "domain_metrics": [{"metric_key": "enrollment_count", "label": "Enrollment Count", "kind": "count", "agg": "count"}],
            "user_metrics": [],
            "overlay_metrics": [{"overlay_key": "students_per_teacher", "label": "Students per Teacher", "requires": [6, 5]}],
            "time_columns": [],
        }


class _FakeDomainVectorService:
    def search_domains(self, **kwargs):
        del kwargs
        return {"results": [{"domain_id": 6, "name": "Enrollment", "score": 0.9}]}


class _FakeLLM:
    def chat_json_with_trace(self, **kwargs):
        del kwargs
        return {
            "parsed": {
                "intent": "aggregate",
                "selects": {
                    "dimensions": [{"column_key": "wt20.county_fips_code", "label": "County"}],
                    "metrics": [{"metric_ref": "overlay:students_per_teacher", "label": "Students per Teacher"}],
                },
                "filters": [],
                "time": {},
                "grouping": {
                    "group_by": ["wt20.county_fips_code"],
                    "order_by": [{"by": "metric:overlay:students_per_teacher", "dir": "desc"}],
                    "limit": 200,
                },
            },
            "content": "{}",
            "raw_text": "{}",
        }


class _FakeLLMWithExplanationSummary:
    def chat_json_with_trace(self, **kwargs):
        user_prompt = str(kwargs.get("user_prompt") or "")
        if "Task: Extract lightweight planning slots" in user_prompt:
            return {
                "parsed": {
                    "intent": "list",
                    "entity": "students",
                    "constraints": [],
                    "time_phrases": [],
                },
                "content": "{}",
                "raw_text": "{}",
            }
        if "Rewrite this explanation into a friendly summary for school staff." in user_prompt:
            return {
                "parsed": {
                    "summary": "I used Staff & Assignments and returned first name, last name, district, and school for the person you asked about."
                },
                "content": "{\"summary\":\"I used Staff & Assignments and returned first name, last name, district, and school for the person you asked about.\"}",
                "raw_text": "{\"summary\":\"I used Staff & Assignments and returned first name, last name, district, and school for the person you asked about.\"}",
            }
        return {
            "parsed": {
                "intent": "list",
                "selects": {
                    "dimensions": [
                        {"column_key": "wt23.first_name"},
                        {"column_key": "wt23.last_name"},
                        {"column_key": "wt20.lea_name"},
                        {"column_key": "wt20.school_name"},
                    ],
                    "metrics": [],
                },
                "filters": [
                    {"column_key": "wt23.first_name", "op": "=", "value": "Jennifer"},
                    {"column_key": "wt23.last_name", "op": "=", "value": "Gilstrap"},
                ],
                "time": {},
                "grouping": {
                    "group_by": ["wt23.first_name", "wt23.last_name", "wt20.lea_name", "wt20.school_name"],
                    "order_by": [],
                    "limit": None,
                },
            },
            "content": "{}",
            "raw_text": "{}",
        }


class _FakeLLMMissingTime:
    def chat_json_with_trace(self, **kwargs):
        user_prompt = str(kwargs.get("user_prompt") or "")
        if "Task: Extract lightweight planning slots" in user_prompt:
            return {
                "parsed": {
                    "intent": "list",
                    "entity": "students",
                    "constraints": [],
                    "time_phrases": [],
                },
                "content": "{}",
                "raw_text": "{}",
            }
        return {
            "parsed": {
                "intent": "list",
                "selects": {
                    "dimensions": [{"column_key": "wt20.county_fips_code", "label": "County"}],
                    "metrics": [],
                },
                "filters": [],
                "grouping": {
                    "group_by": ["wt20.county_fips_code"],
                    "order_by": [],
                    "limit": 200,
                },
            },
            "content": "{}",
            "raw_text": "{}",
        }


class _FakeValueAliasResolver:
    def __init__(self, rows=None, *, should_raise: bool = False) -> None:
        self.rows = list(rows or [])
        self.should_raise = should_raise

    def resolve(self, *, prompt: str):
        del prompt
        if self.should_raise:
            raise RuntimeError("boom")
        return list(self.rows)


class _FakeSemanticGroundingService:
    def __init__(self) -> None:
        self.calls = []

    def resolve_alias_constraints(self, *, prompt: str):
        del prompt
        return [
            {
                "kind": "unknown",
                "text": "US",
                "op": "eq",
                "value_hint": "United States",
                "notes": "semantic_alias:COUNTRY",
            }
        ]

    def build_grounding_bundle(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SemanticGroundingBundle(
            alias_constraints=[
                {
                    "kind": "unknown",
                    "text": "US",
                    "op": "eq",
                    "value_hint": "United States",
                    "notes": "semantic_alias:COUNTRY",
                }
            ],
            warnings=[],
        )


class _RankingSemanticGroundingService:
    def __init__(self) -> None:
        self.calls = []

    def build_grounding_bundle(self, **kwargs):
        self.calls.append(dict(kwargs))
        domain_id = int(kwargs["base_domain_id"])
        if domain_id == 5:
            candidates = SemanticCandidatePayload(
                prompt="prompt",
                workspace_id="ws-1",
                base_domain_id=5,
                base_domain_key="STAFF",
                metric_candidates=[
                    SemanticConceptCandidate(concept_key="STAFF_COUNT", label="Staff Count", metric_ref="domain_metric:staff_count")
                ],
                dimension_candidates=[
                    SemanticConceptCandidate(concept_key="STAFF_NAME", label="Staff Name", source_column_key="wt23.staff_unique_id")
                ],
                filter_candidates=[
                    SemanticConceptCandidate(concept_key="SCHOOL_NAME", label="School Name", source_column_key="wt20.school_name")
                ],
                metadata={"semantic_source": "registry"},
            )
            return SemanticGroundingBundle(candidates=candidates, alias_constraints=[{"value_hint": "Rossview Elementary"}])
        candidates = SemanticCandidatePayload(
            prompt="prompt",
            workspace_id="ws-1",
            base_domain_id=6,
            base_domain_key="STUDENTS",
            dimension_candidates=[
                SemanticConceptCandidate(concept_key="STUDENT_NAME", label="Student Name", source_column_key="wt24.student_unique_id")
            ],
            metadata={"semantic_source": "fallback_capabilities"},
        )
        return SemanticGroundingBundle(candidates=candidates, alias_constraints=[])

    def resolve_alias_constraints(self, *, prompt: str):
        del prompt
        return []


class _FakePlannerRerankPolicyService:
    def __init__(self, rows=None) -> None:
        self.rows = list(rows or [])

    def get_applicable_policies(self, *, workspace_id: str, base_domain_id: int):
        del workspace_id, base_domain_id
        return list(self.rows)


class _FakeLLMNameFilters:
    def __init__(self) -> None:
        self.calls = 0

    def chat_json_with_trace(self, **kwargs):
        self.calls += 1
        user_prompt = str(kwargs.get("user_prompt") or "")
        if "Task: Extract lightweight planning slots" in user_prompt:
            return {
                "parsed": {
                    "intent": "list",
                    "entity": "students",
                    "constraints": [
                        {"kind": "unknown", "text": "first name Holden", "op": "eq", "value_hint": "Holden", "notes": None},
                        {"kind": "unknown", "text": "last name Black", "op": "eq", "value_hint": "Black", "notes": None},
                    ],
                    "time_phrases": [],
                },
                "content": "{}",
                "raw_text": "{}",
            }
        return {
            "parsed": {
                "intent": "list",
                "selects": {
                    "dimensions": [{"column_key": "wt24.k_student", "label": "Student"}],
                    "metrics": [],
                },
                "filters": [
                    {"column_key": "wt24.first_name", "op": "equals", "value": "Holden"},
                    {"column_key": "wt24.last_name", "op": "equals", "value": "Black"},
                ],
                "time": {},
                "grouping": {
                    "group_by": ["wt24.k_student"],
                    "order_by": [],
                    "limit": 200,
                },
            },
            "content": "{}",
            "raw_text": "{}",
        }


class _FakeLLMStudentIdentityPlan:
    def chat_json_with_trace(self, **kwargs):
        user_prompt = str(kwargs.get("user_prompt") or "")
        if "Task: Extract lightweight planning slots" in user_prompt:
            return {
                "parsed": {
                    "intent": "list",
                    "entity": "students",
                    "constraints": [],
                    "time_phrases": [],
                },
                "content": "{}",
                "raw_text": "{}",
            }
        return {
            "parsed": {
                "intent": "list",
                "selects": {
                    "dimensions": [
                        {"column_key": "wt24.student_unique_id"},
                        {"column_key": "wt24.first_name"},
                        {"column_key": "wt24.last_name"},
                    ],
                    "metrics": [],
                },
                "filters": [{"column_key": "wt24.birth_country", "op": "ne", "value": "US"}],
                "time": {},
                "grouping": {
                    "group_by": ["wt24.student_unique_id", "wt24.first_name", "wt24.last_name"],
                    "order_by": [],
                    "limit": None,
                },
            },
            "content": "{}",
            "raw_text": "{}",
        }


def test_required_column_keys_prefers_account_and_territory_name_for_group_by_prompt() -> None:
    rows = [
        {"column_key": "wt178.account_id", "column_name": "account_id"},
        {"column_key": "wt178.account_type", "column_name": "account_type"},
        {"column_key": "wt178.account_name", "column_name": "account_name"},
        {"column_key": "wt187.territory_id", "column_name": "territory_id"},
        {"column_key": "wt187.territory_name", "column_name": "territory_name"},
    ]
    keys = _required_column_keys(prompt="Show total sales by account and territory", rows=rows)
    assert "wt178.account_name" in keys
    assert "wt187.territory_name" in keys


def test_column_heuristic_boost_prefers_name_over_id_and_type_for_grouping() -> None:
    prompt = "Show total sales by account and territory"
    account_name = _column_heuristic_boost(prompt=prompt, row={"column_key": "wt178.account_name", "column_name": "account_name"})
    account_type = _column_heuristic_boost(prompt=prompt, row={"column_key": "wt178.account_type", "column_name": "account_type"})
    territory_name = _column_heuristic_boost(
        prompt=prompt,
        row={"column_key": "wt187.territory_name", "column_name": "territory_name"},
    )
    territory_id = _column_heuristic_boost(prompt=prompt, row={"column_key": "wt187.territory_id", "column_name": "territory_id"})
    assert account_name > account_type
    assert territory_name > territory_id


class _FakeStaffCapabilitiesService:
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
                    "column_key": "wt30.position_title",
                    "label": "Position Title",
                    "data_type": "string",
                    "filterable": True,
                    "workspace_table_id": 30,
                    "model_column_id": 602,
                    "column_name": "position_title",
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
            ],
            "domain_metrics": [
                {
                    "metric_key": "staff_count",
                    "label": "Staff Count",
                    "kind": "count",
                    "agg": "count",
                }
            ],
            "user_metrics": [],
            "overlay_metrics": [],
            "time_columns": [],
        }


class _FakeLLMWithNextActions:
    def chat_json_with_trace(self, **kwargs):
        user_prompt = str(kwargs.get("user_prompt") or "")
        if "Task: Extract lightweight planning slots" in user_prompt:
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
        if "Generate next action suggestions for this completed plan context." in user_prompt:
            return {
                "parsed": {
                    "next_actions": [
                        {
                            "label": "Assistant Principals",
                            "prompt": "Show assistant principals at Barksdale Elementary",
                            "reason": "This keeps the same school context and changes role focus.",
                            "intent": "list",
                            "dimensions": ["wt23.first_name", "wt23.last_name", "wt30.position_title"],
                            "filters": [
                                {"column_key": "wt20.school_name", "op": "eq", "value": "Barksdale Elementary"},
                                {"column_key": "wt30.position_title", "op": "eq", "value": "Assistant Principal"},
                            ],
                            "metrics": [],
                            "confidence": 0.91,
                        },
                        {
                            "label": "Out of Domain Suggestion",
                            "prompt": "Show transportation routes for Barksdale Elementary",
                            "reason": "This should be rejected by validator because columns are outside domain.",
                            "intent": "list",
                            "dimensions": ["wt999.route_name"],
                            "filters": [{"column_key": "wt999.route_name", "op": "eq", "value": "Route A"}],
                            "metrics": [],
                            "confidence": 0.83,
                        },
                        {
                            "label": "Staff Count by Role",
                            "prompt": "Show staff count by position title at Barksdale Elementary",
                            "reason": "Adds a quick aggregate in the same domain and school context.",
                            "intent": "aggregate",
                            "dimensions": ["wt30.position_title"],
                            "filters": [{"column_key": "wt20.school_name", "op": "eq", "value": "Barksdale Elementary"}],
                            "metrics": ["domain_metric:staff_count"],
                            "confidence": 0.88,
                        },
                    ]
                },
                "content": "{\"next_actions\":[]}",
                "raw_text": "{\"next_actions\":[]}",
            }
        return {
            "parsed": {
                "intent": "list",
                "selects": {
                    "dimensions": [
                        {"column_key": "wt30.position_title"},
                        {"column_key": "wt23.first_name"},
                        {"column_key": "wt23.last_name"},
                    ],
                    "metrics": [],
                },
                "filters": [
                    {"column_key": "wt30.position_title", "op": "=", "value": "Principal"},
                    {"column_key": "wt20.school_name", "op": "=", "value": "Barksdale Elementary"},
                ],
                "time": {},
                "grouping": {
                    "group_by": ["wt30.position_title", "wt23.first_name", "wt23.last_name"],
                    "order_by": [],
                    "limit": None,
                },
            },
            "content": "{}",
            "raw_text": "{}",
        }


def test_golden_students_per_teacher_by_county_prefers_overlay_metric() -> None:
    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "base_domain_id": 6,
            "prompt": "students per teacher by county",
            "debug": True,
        },
        user_id="user-1",
    )

    assert out["validation"]["is_valid"] is True
    assert out["plan_json_v2"]["base_domain_id"] == 6
    assert out["plan_json_v2"]["domain_name"] == "domain_6"
    assert out["technical_details"]["trace_id"] == out["trace_id"]
    assert out["technical_details"]["conversation_id"] == out["conversation_id"]
    assert out["plan_json_v2"]["selects"]["metrics"][0]["metric_ref"] == "overlay:students_per_teacher"
    assert out["plan_json_v2"]["selects"]["dimensions"][0]["column_key"] == "wt20.county_fips_code"
    assert "explanation" in out
    assert out["explanation"]["domain"]["selected_domain_id"] == 6
    assert out["explanation"]["metrics"][0]["metric_ref"] == "overlay:students_per_teacher"
    assert "I used the" in out["explanation"]["summary"]
    assert out["explanation"]["domain"]["reason"]
    assert out["debug"]["shared_pipeline"]["domain_selection"]["pipeline_name"] == "planner_domain_selection_pipeline"
    trace_nodes = out["debug"]["shared_pipeline"]["domain_selection"]["trace_nodes"]
    assert [node["node"] for node in trace_nodes] == [
        "normalize_text",
        "resolve_capabilities",
        "extract_signals",
        "apply_policy_rerank",
    ]
    sql_metrics = ((out["sql_json"].get("aggs") or {}).get("metrics") or [])
    assert sql_metrics
    assert sql_metrics[0]["fn"] == "overlay_metric"
    assert sql_metrics[0]["overlay_key"] == "students_per_teacher"


def test_plan_pipeline_profile_can_be_enabled_per_request(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_TIMING_PROFILE_ENABLED", False)
    log_file = str(tmp_path / "plan_domain_pipeline_timing.log")
    monkeypatch.setattr(
        planner_domain_service_module,
        "QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE",
        log_file,
    )
    monkeypatch.setattr(
        pipeline_trace_module,
        "QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE",
        log_file,
    )
    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "base_domain_id": 6,
            "prompt": "students per teacher by county",
            "profile_pipeline": True,
        },
        user_id="user-1",
    )

    profile_steps = list(out.get("pipeline_profile") or [])
    assert profile_steps
    step_names = {str(row.get("step") or "") for row in profile_steps}
    assert "domain_selection" in step_names
    assert "llm_plan" in step_names
    assert int(out["timings_ms"].get("total") or 0) >= 0


def test_plan_fast_mode_is_passed_to_slot_and_plan_calls(monkeypatch) -> None:
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_ENABLED", False)
    captured = {"slot_fast_mode": None, "plan_fast_mode": None}

    def _fake_slots(
        self,
        *,
        normalized_prompt,
        workspace_id,
        base_domain_id,
        conversation_context=None,
        fast_mode=False,
    ):
        del self, normalized_prompt, workspace_id, base_domain_id, conversation_context
        captured["slot_fast_mode"] = fast_mode
        return SlotExtractionResult(
            payload={"intent": "list", "entity": "students", "constraints": [], "time_phrases": []},
            raw_content="{}",
            attempts=1,
            repaired=False,
        )

    def _fake_plan(
        self,
        *,
        normalized_prompt,
        workspace_id,
        base_domain_id,
        capabilities,
        schema,
        slot_hints,
        validation_feedback="",
        retry_hint="",
        conversation_context=None,
        fast_mode=False,
    ):
        del (
            self,
            normalized_prompt,
            workspace_id,
            base_domain_id,
            capabilities,
            schema,
            slot_hints,
            validation_feedback,
            retry_hint,
            conversation_context,
        )
        captured["plan_fast_mode"] = fast_mode
        return LLMPlanResult(
            plan_json={
                "intent": "list",
                "selects": {"dimensions": [{"column_key": "wt20.county_fips_code"}], "metrics": []},
                "filters": [],
                "time": {},
                "grouping": {"group_by": ["wt20.county_fips_code"], "order_by": [], "limit": 200},
            },
            raw_content="{}",
            attempts=1,
            repaired=False,
        )

    monkeypatch.setattr(LLMPlanningService, "_call_llm_slots", _fake_slots)
    monkeypatch.setattr(LLMPlanningService, "_call_llm_plan", _fake_plan)

    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "base_domain_id": 6,
            "prompt": "students per teacher by county",
            "fast_mode": True,
        },
        user_id="user-1",
    )

    assert out["validation"]["is_valid"] is True
    assert captured["slot_fast_mode"] is True
    assert captured["plan_fast_mode"] is True
    assert out["technical_details"]["fast_mode"] is True


def test_fast_mode_retries_when_first_plan_is_invalid(monkeypatch) -> None:
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_ENABLED", False)
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_LLM_EXPLANATION_ENABLED", False)

    call_counter = {"plan_calls": 0}

    def _fake_slots(
        self,
        *,
        normalized_prompt,
        workspace_id,
        base_domain_id,
        conversation_context=None,
        fast_mode=False,
    ):
        del self, normalized_prompt, workspace_id, base_domain_id, conversation_context, fast_mode
        return SlotExtractionResult(
            payload={"intent": "list", "entity": "students", "constraints": [], "time_phrases": []},
            raw_content="{}",
            attempts=1,
            repaired=False,
        )

    def _fake_plan(
        self,
        *,
        normalized_prompt,
        workspace_id,
        base_domain_id,
        capabilities,
        schema,
        slot_hints,
        validation_feedback="",
        retry_hint="",
        conversation_context=None,
        fast_mode=False,
    ):
        del (
            self,
            normalized_prompt,
            workspace_id,
            base_domain_id,
            capabilities,
            schema,
            slot_hints,
            validation_feedback,
            retry_hint,
            conversation_context,
        )
        call_counter["plan_calls"] += 1
        if call_counter["plan_calls"] == 1:
            return LLMPlanResult(
                plan_json={
                    "intent": "list",
                    "selects": {"dimensions": [{"column_key": "wt999.not_allowed"}], "metrics": []},
                    "filters": [],
                    "time": {},
                    "grouping": {"group_by": ["wt999.not_allowed"], "order_by": [], "limit": 200},
                },
                raw_content="{}",
                attempts=1,
                repaired=False,
            )
        return LLMPlanResult(
            plan_json={
                "intent": "list",
                "selects": {"dimensions": [{"column_key": "wt20.county_fips_code"}], "metrics": []},
                "filters": [],
                "time": {},
                "grouping": {"group_by": ["wt20.county_fips_code"], "order_by": [], "limit": 200},
            },
            raw_content="{}",
            attempts=1,
            repaired=False,
        )

    monkeypatch.setattr(LLMPlanningService, "_call_llm_slots", _fake_slots)
    monkeypatch.setattr(LLMPlanningService, "_call_llm_plan", _fake_plan)

    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "base_domain_id": 6,
            "prompt": "students per teacher by county",
            "fast_mode": True,
        },
        user_id="user-1",
    )

    assert out["validation"]["is_valid"] is True
    assert call_counter["plan_calls"] == 2


def test_unified_llm_invalid_json_falls_back_to_legacy_path(monkeypatch) -> None:
    monkeypatch.setattr(planner_domain_service_module, "PLANNER_UNIFIED_LLM", True)
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_ENABLED", False)
    calls = {"slots": 0, "plan": 0}

    def _fake_unified(
        self,
        *,
        prompt,
        normalized_prompt,
        workspace_id,
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
            base_domain_id,
            domain_name,
            capabilities,
            conversation_context,
            trace_id,
            fast_mode,
            grounding_bundle,
        )
        raise ForgeError(
            "plan_domain unified invalid model JSON",
            status_code=502,
            details={"finish_reason_second": "length"},
        )

    def _fake_slots(
        self,
        *,
        normalized_prompt,
        workspace_id,
        base_domain_id,
        conversation_context=None,
        fast_mode=False,
    ):
        del self, normalized_prompt, workspace_id, base_domain_id, conversation_context, fast_mode
        calls["slots"] += 1
        return SlotExtractionResult(
            payload={"intent": "list", "entity": "students", "constraints": [], "time_phrases": []},
            raw_content="{}",
            attempts=1,
            repaired=False,
        )

    def _fake_plan(
        self,
        *,
        normalized_prompt,
        workspace_id,
        base_domain_id,
        capabilities,
        schema,
        slot_hints,
        validation_feedback="",
        retry_hint="",
        conversation_context=None,
        fast_mode=False,
    ):
        del (
            self,
            normalized_prompt,
            workspace_id,
            base_domain_id,
            capabilities,
            schema,
            slot_hints,
            validation_feedback,
            retry_hint,
            conversation_context,
            fast_mode,
        )
        calls["plan"] += 1
        return LLMPlanResult(
            plan_json={
                "intent": "list",
                "selects": {"dimensions": [{"column_key": "wt20.county_fips_code"}], "metrics": []},
                "filters": [],
                "time": {},
                "grouping": {"group_by": ["wt20.county_fips_code"], "order_by": [], "limit": 200},
            },
            raw_content="{}",
            attempts=1,
            repaired=False,
        )

    monkeypatch.setattr(LLMPlanningService, "_call_llm_unified", _fake_unified)
    monkeypatch.setattr(LLMPlanningService, "_call_llm_slots", _fake_slots)
    monkeypatch.setattr(LLMPlanningService, "_call_llm_plan", _fake_plan)

    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )
    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "base_domain_id": 6,
            "prompt": "show students by county",
            "debug": True,
        },
        user_id="user-1",
    )

    assert out["validation"]["is_valid"] is True
    assert calls["slots"] == 1
    assert calls["plan"] == 1
    assert out["technical_details"]["planner_unified_llm"] is True
    assert out["debug"]["unified_llm_trace"]["fallback_to_legacy_llm_path"] is True


def test_explanation_summary_can_be_polished_by_llm(monkeypatch) -> None:
    class _StaffCapsService:
        def get_domain_capabilities(self, *, workspace_id, user_id, domain_id):
            del workspace_id, user_id
            assert domain_id == 5
            return {
                "domain_id": 5,
                "domain_version": 1,
                "dimensions": [
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
                        "column_key": "wt20.lea_name",
                        "label": "District",
                        "data_type": "string",
                        "filterable": True,
                        "workspace_table_id": 20,
                        "model_column_id": 266,
                        "column_name": "lea_name",
                    },
                    {
                        "column_key": "wt20.school_name",
                        "label": "School Name",
                        "data_type": "string",
                        "filterable": True,
                        "workspace_table_id": 20,
                        "model_column_id": 99,
                        "column_name": "school_name",
                    },
                ],
                "domain_metrics": [],
                "user_metrics": [],
                "overlay_metrics": [],
                "time_columns": [],
            }

    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_LLM_EXPLANATION_ENABLED", True)
    svc = PlannerDomainService(
        capabilities_service=_StaffCapsService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLMWithExplanationSummary(),
    )

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "base_domain_id": 5,
            "prompt": "Show me where Jennifer Gilstrap works",
            "debug": True,
        },
        user_id="user-1",
    )

    assert out["validation"]["is_valid"] is True
    assert out["explanation"]["summary_source"] == "llm"
    assert "I used Staff & Assignments" in out["explanation"]["summary"]


def test_next_actions_generated_and_validated_in_domain(monkeypatch) -> None:
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_ENABLED", True)
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_MAX_ITEMS", 4)
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_NEXT_ACTIONS_ASYNC_DEFAULT", False)
    svc = PlannerDomainService(
        capabilities_service=_FakeStaffCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLMWithNextActions(),
    )

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "base_domain_id": 5,
            "prompt": "Show me the principal for Barksdale Elementary",
            "debug": True,
        },
        user_id="user-1",
    )

    next_actions = list(out.get("next_actions") or [])
    assert len(next_actions) == 2
    assert all("wt999" not in str(item) for item in next_actions)
    assert any(item.get("intent") == "aggregate" for item in next_actions)
    assert any(item.get("metrics") == ["domain_metric:staff_count"] for item in next_actions)


def test_plan_domain_can_defer_next_actions_async(monkeypatch) -> None:
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_NEXT_ACTIONS_ASYNC_DEFAULT", False)

    def _fail_if_called(*args, **kwargs):
        del args, kwargs
        raise AssertionError("maybe_generate should not be called when async is enabled")

    from app.services.planner_domain.next_actions_service import NextActionsService
    monkeypatch.setattr(NextActionsService, "maybe_generate", _fail_if_called)
    svc = PlannerDomainService(
        capabilities_service=_FakeStaffCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLMWithNextActions(),
    )

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "base_domain_id": 5,
            "prompt": "Show me the principal for Barksdale Elementary",
            "next_actions_async": True,
        },
        user_id="user-1",
    )

    assert out["next_actions_status"] == "deferred"
    assert out["next_actions"] == []


def test_generate_next_actions_from_plan_payload(monkeypatch) -> None:
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_LLM_NEXT_ACTIONS_ENABLED", True)
    svc = PlannerDomainService(
        capabilities_service=_FakeStaffCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLMWithNextActions(),
    )

    out = svc.generate_next_actions(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "prompt": "Show me the principal for Barksdale Elementary",
            "plan_json_v2": {
                "base_domain_id": 5,
                "domain_name": "Staff & Assignments",
                "intent": "list",
                "selects": {
                    "dimensions": [
                        {"column_key": "wt30.position_title"},
                        {"column_key": "wt23.first_name"},
                        {"column_key": "wt23.last_name"},
                    ],
                    "metrics": [],
                },
                "filters": [
                    {"column_key": "wt30.position_title", "op": "=", "value": "Principal"},
                    {"column_key": "wt20.school_name", "op": "=", "value": "Barksdale Elementary"},
                ],
            },
            "conversation_id": "pdc_abc123",
            "trace_id": "trace-abc",
        },
        user_id="user-1",
    )

    assert out["next_actions_status"] == "ready"
    assert len(list(out.get("next_actions") or [])) >= 1
    assert out["trace_id"] == "trace-abc"
    assert out["conversation_id"] == "pdc_abc123"


def test_plan_tolerates_conversation_store_backend_failures() -> None:
    class _FailingConversationStore:
        def get_state(self, **kwargs):
            del kwargs
            raise ValkeyError("valkey unavailable")

        def save_state(self, **kwargs):
            del kwargs

    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
        conversation_store=_FailingConversationStore(),
    )

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "base_domain_id": 6,
            "prompt": "list students by county",
        },
        user_id="user-1",
    )

    assert out["validation"]["is_valid"] is True


def test_plan_surfaces_unexpected_conversation_store_errors() -> None:
    class _FailingConversationStore:
        def get_state(self, **kwargs):
            del kwargs
            raise AssertionError("unexpected conversation store failure")

        def save_state(self, **kwargs):
            del kwargs

    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
        conversation_store=_FailingConversationStore(),
    )

    with pytest.raises(AssertionError, match="unexpected conversation store failure"):
        svc.plan(
            {
                "workspace_id": "ws-1",
                "vertical_norm": "education",
                "base_domain_id": 6,
                "prompt": "list students by county",
            },
            user_id="user-1",
        )


def test_plan_tolerates_optional_time_policy_failures() -> None:
    class _FailingTimePolicyService:
        def get_policy(self, **kwargs):
            del kwargs
            raise SQLAlchemyError("db unavailable")

    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
        domain_time_policy_service=_FailingTimePolicyService(),
    )

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "base_domain_id": 6,
            "prompt": "list students by county",
        },
        user_id="user-1",
    )

    assert out["validation"]["is_valid"] is True


def test_plan_surfaces_unexpected_time_policy_errors() -> None:
    class _FailingTimePolicyService:
        def get_policy(self, **kwargs):
            del kwargs
            raise AssertionError("unexpected time policy failure")

    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
        domain_time_policy_service=_FailingTimePolicyService(),
    )

    with pytest.raises(AssertionError, match="unexpected time policy failure"):
        svc.plan(
            {
                "workspace_id": "ws-1",
                "vertical_norm": "education",
                "base_domain_id": 6,
                "prompt": "list students by county",
            },
            user_id="user-1",
        )


def test_plan_accepts_llm_payload_missing_time_block() -> None:
    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLMMissingTime(),
    )

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "base_domain_id": 6,
            "prompt": "list students by county",
            "debug": True,
        },
        user_id="user-1",
    )

    assert out["validation"]["is_valid"] is True
    assert isinstance(out["plan_json_v2"].get("time"), dict)
    assert out["plan_json_v2"]["time"] == {}


def test_compact_capabilities_prepends_student_identity_for_show_students_prompt() -> None:
    _ = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )

    capabilities = {
        "domain_id": 6,
        "domain_version": 1,
        "dimensions": [
            {
                "column_key": "wt24.birth_country",
                "column_name": "birth_country",
                "filterable": True,
                "workspace_table_id": 24,
            },
            {
                "column_key": "wt24.student_unique_id",
                "column_name": "student_unique_id",
                "semantic_concept_key": "STUDENT_ID",
                "filterable": True,
                "workspace_table_id": 24,
            },
            {
                "column_key": "wt24.first_name",
                "column_name": "first_name",
                "semantic_concept_key": "STUDENT_FIRST_NAME",
                "filterable": True,
                "workspace_table_id": 24,
            },
            {
                "column_key": "wt24.last_name",
                "column_name": "last_name",
                "semantic_concept_key": "STUDENT_LAST_NAME",
                "filterable": True,
                "workspace_table_id": 24,
            },
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }
    shortlisted = [{"column_key": "wt24.birth_country", "column_name": "birth_country", "workspace_table_id": 24}]

    compact = DomainSelectionService.compact_capabilities_for_llm(
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
        prompt="Show students not born in the US",
    )

    first_three = [row["column_key"] for row in compact["dimensions"][:3]]
    assert first_three == ["wt24.student_unique_id", "wt24.first_name", "wt24.last_name"]


def test_compact_capabilities_prepends_student_identity_from_slot_hints() -> None:
    _ = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )

    capabilities = {
        "domain_id": 6,
        "domain_version": 1,
        "dimensions": [
            {
                "column_key": "wt24.birth_country",
                "column_name": "birth_country",
                "filterable": True,
                "workspace_table_id": 24,
            },
            {
                "column_key": "wt24.student_unique_id",
                "column_name": "student_unique_id",
                "semantic_concept_key": "STUDENT_ID",
                "filterable": True,
                "workspace_table_id": 24,
            },
            {
                "column_key": "wt24.first_name",
                "column_name": "first_name",
                "semantic_concept_key": "STUDENT_FIRST_NAME",
                "filterable": True,
                "workspace_table_id": 24,
            },
            {
                "column_key": "wt24.last_name",
                "column_name": "last_name",
                "semantic_concept_key": "STUDENT_LAST_NAME",
                "filterable": True,
                "workspace_table_id": 24,
            },
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }
    shortlisted = [{"column_key": "wt24.birth_country", "column_name": "birth_country", "workspace_table_id": 24}]

    compact = DomainSelectionService.compact_capabilities_for_llm(
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
        prompt="students not born in the US",
        slot_hints={"intent": "list", "entity": "students"},
    )

    first_three = [row["column_key"] for row in compact["dimensions"][:3]]
    assert first_three == ["wt24.student_unique_id", "wt24.first_name", "wt24.last_name"]


def test_compact_capabilities_projection_policy_resolves_concept_keys() -> None:
    capabilities = {
        "domain_id": 6,
        "domain_version": 1,
        "dimensions": [
            {
                "column_key": "wt24.birth_country",
                "column_name": "birth_country",
                "filterable": True,
                "workspace_table_id": 24,
            },
            {
                "column_key": "wt24.student_lookup_key",
                "column_name": "learner_lookup_key",
                "semantic_concept_key": "STUDENT_ID",
                "filterable": True,
                "workspace_table_id": 24,
            },
            {
                "column_key": "wt24.given_name_text",
                "column_name": "given_name_text",
                "semantic_concept_key": "STUDENT_FIRST_NAME",
                "filterable": True,
                "workspace_table_id": 24,
            },
            {
                "column_key": "wt24.family_name_text",
                "column_name": "family_name_text",
                "semantic_concept_key": "STUDENT_LAST_NAME",
                "filterable": True,
                "workspace_table_id": 24,
            },
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }
    shortlisted = [{"column_key": "wt24.birth_country", "column_name": "birth_country", "workspace_table_id": 24}]

    compact = DomainSelectionService.compact_capabilities_for_llm(
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
        prompt="Show students not born in the US",
    )

    first_three = [row["column_key"] for row in compact["dimensions"][:3]]
    assert first_three == ["wt24.student_lookup_key", "wt24.given_name_text", "wt24.family_name_text"]


def test_compact_capabilities_includes_nativity_filter_columns() -> None:
    _ = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )

    capabilities = {
        "domain_id": 7,
        "domain_version": 1,
        "dimensions": [
            {
                "column_key": "wt24.k_student",
                "column_name": "k_student",
                "filterable": True,
                "workspace_table_id": 24,
            },
            {
                "column_key": "wt24.first_name",
                "column_name": "first_name",
                "filterable": True,
                "workspace_table_id": 24,
            },
            {
                "column_key": "wt24.birth_country",
                "column_name": "birth_country",
                "filterable": True,
                "workspace_table_id": 24,
            },
        ],
        "time_columns": [
            {
                "column_key": "wt24.date_entered_us",
                "column_name": "date_entered_us",
                "filterable": True,
                "workspace_table_id": 24,
            }
        ],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }
    shortlisted = [
        {"column_key": "wt24.k_student"},
        {"column_key": "wt24.first_name"},
    ]

    compact = DomainSelectionService.compact_capabilities_for_llm(
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
        prompt="list all the students not born in the us",
    )

    dim_keys = {row["column_key"] for row in compact["dimensions"]}
    filter_keys = {row["column_key"] for row in compact["filter_columns"]}
    assert "wt24.birth_country" not in dim_keys
    assert "wt24.birth_country" in filter_keys


def test_compact_capabilities_prepends_school_listing_identity_columns() -> None:
    _ = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )

    capabilities = {
        "domain_id": 4,
        "domain_version": 1,
        "dimensions": [
            {
                "column_key": "wt20.nces_school_code",
                "column_name": "nces_school_code",
                "filterable": True,
                "workspace_table_id": 20,
            },
            {
                "column_key": "wt20.school_name",
                "column_name": "school_name",
                "filterable": True,
                "workspace_table_id": 20,
            },
            {
                "column_key": "wt20.lea_name",
                "column_name": "lea_name",
                "filterable": True,
                "workspace_table_id": 20,
            },
            {
                "column_key": "wt20.school_number",
                "column_name": "school_number",
                "filterable": True,
                "workspace_table_id": 20,
            },
            {
                "column_key": "wt20.city",
                "column_name": "city",
                "filterable": True,
                "workspace_table_id": 20,
            },
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }
    shortlisted = [{"column_key": "wt20.nces_school_code", "column_name": "nces_school_code", "workspace_table_id": 20}]

    compact = DomainSelectionService.compact_capabilities_for_llm(
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
        prompt="Show me all the schools in Clarksville, TN",
    )

    first_three = [row["column_key"] for row in compact["dimensions"][:3]]
    assert first_three == ["wt20.school_name", "wt20.lea_name", "wt20.school_number"]


def test_compact_capabilities_city_state_prefers_state_code_over_state_school_code() -> None:
    _ = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )

    capabilities = {
        "domain_id": 4,
        "domain_version": 1,
        "dimensions": [
            {
                "column_key": "wt20.school_name",
                "column_name": "school_name",
                "filterable": True,
                "workspace_table_id": 20,
            },
            {
                "column_key": "wt20.lea_name",
                "column_name": "lea_name",
                "filterable": True,
                "workspace_table_id": 20,
            },
            {
                "column_key": "wt20.school_number",
                "column_name": "school_number",
                "filterable": True,
                "workspace_table_id": 20,
            },
            {
                "column_key": "wt20.city",
                "column_name": "city",
                "filterable": True,
                "workspace_table_id": 20,
            },
            {
                "column_key": "wt20.state_code",
                "column_name": "state_code",
                "filterable": True,
                "workspace_table_id": 20,
            },
            {
                "column_key": "wt20.state_school_code",
                "column_name": "state_school_code",
                "filterable": True,
                "workspace_table_id": 20,
            },
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }
    shortlisted = [{"column_key": "wt20.state_school_code", "column_name": "state_school_code", "workspace_table_id": 20}]

    compact = DomainSelectionService.compact_capabilities_for_llm(
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
        prompt="Show me all the schools in Clarksville, TN",
    )

    dim_keys = [row["column_key"] for row in compact["dimensions"]]
    filter_keys = [row["column_key"] for row in compact["filter_columns"]]
    assert "wt20.state_code" in dim_keys
    assert "wt20.state_school_code" not in dim_keys
    assert "wt20.state_code" in filter_keys
    assert "wt20.state_school_code" not in filter_keys


def test_compact_capabilities_staff_school_name_filter_avoids_k_school() -> None:
    _ = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )

    capabilities = {
        "domain_id": 5,
        "domain_version": 1,
        "dimensions": [
            {
                "column_key": "wt23.first_name",
                "column_name": "first_name",
                "filterable": True,
                "workspace_table_id": 23,
            },
            {
                "column_key": "wt30.k_school",
                "column_name": "k_school",
                "semantic_concept_key": "SCHOOL_ID",
                "filterable": True,
                "workspace_table_id": 30,
            },
            {
                "column_key": "wt20.school_name",
                "column_name": "school_name",
                "semantic_concept_key": "SCHOOL_NAME",
                "filterable": True,
                "workspace_table_id": 20,
            },
            {
                "column_key": "wt20.lea_name",
                "column_name": "lea_name",
                "semantic_concept_key": "DISTRICT_NAME",
                "filterable": True,
                "workspace_table_id": 20,
            },
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }
    shortlisted = [{"column_key": "wt30.k_school", "column_name": "k_school", "workspace_table_id": 30}]

    compact = DomainSelectionService.compact_capabilities_for_llm(
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
        prompt="Show me all the staff for Rossview Elementary",
    )

    filter_keys = [row["column_key"] for row in compact["filter_columns"]]
    assert "wt20.school_name" in filter_keys
    assert "wt30.k_school" not in filter_keys


def test_compact_capabilities_principal_school_name_filter_avoids_k_school() -> None:
    _ = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )

    capabilities = {
        "domain_id": 5,
        "domain_version": 1,
        "dimensions": [
            {
                "column_key": "wt30.position_title",
                "column_name": "position_title",
                "filterable": True,
                "workspace_table_id": 30,
            },
            {
                "column_key": "wt30.k_school",
                "column_name": "k_school",
                "semantic_concept_key": "SCHOOL_ID",
                "filterable": True,
                "workspace_table_id": 30,
            },
            {
                "column_key": "wt20.school_name",
                "column_name": "school_name",
                "semantic_concept_key": "SCHOOL_NAME",
                "filterable": True,
                "workspace_table_id": 20,
            },
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }
    shortlisted = [{"column_key": "wt30.k_school", "column_name": "k_school", "workspace_table_id": 30}]

    compact = DomainSelectionService.compact_capabilities_for_llm(
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
        prompt="Show me the principal for Barksdale Elementary",
    )

    filter_keys = [row["column_key"] for row in compact["filter_columns"]]
    assert "wt20.school_name" in filter_keys
    assert "wt30.k_school" not in filter_keys


def test_compact_capabilities_explicit_school_key_request_keeps_school_id_filter() -> None:
    capabilities = {
        "domain_id": 5,
        "domain_version": 1,
        "dimensions": [
            {
                "column_key": "wt30.k_school",
                "column_name": "k_school",
                "semantic_concept_key": "SCHOOL_ID",
                "filterable": True,
                "workspace_table_id": 30,
            },
            {
                "column_key": "wt20.school_name",
                "column_name": "school_name",
                "semantic_concept_key": "SCHOOL_NAME",
                "filterable": True,
                "workspace_table_id": 20,
            },
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }
    shortlisted = [{"column_key": "wt30.k_school", "column_name": "k_school", "workspace_table_id": 30}]

    compact = DomainSelectionService.compact_capabilities_for_llm(
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
        prompt="Show me the school id for Barksdale Elementary",
    )

    filter_keys = [row["column_key"] for row in compact["filter_columns"]]
    assert "wt30.k_school" in filter_keys


def test_compact_capabilities_staff_role_filter_prefers_position_title_over_classification() -> None:
    _ = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )

    capabilities = {
        "domain_id": 5,
        "domain_version": 1,
        "dimensions": [
            {
                "column_key": "wt30.staff_classification",
                "column_name": "staff_classification",
                "semantic_concept_key": "STAFF_CLASSIFICATION",
                "filterable": True,
                "workspace_table_id": 30,
            },
            {
                "column_key": "wt30.position_title",
                "column_name": "position_title",
                "semantic_concept_key": "STAFF_ROLE",
                "filterable": True,
                "workspace_table_id": 30,
            },
            {
                "column_key": "wt31.classroom_position",
                "column_name": "classroom_position",
                "semantic_concept_key": "STAFF_ROLE",
                "filterable": True,
                "workspace_table_id": 31,
            },
            {
                "column_key": "wt20.school_name",
                "column_name": "school_name",
                "filterable": True,
                "workspace_table_id": 20,
            },
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }
    shortlisted = [
        {
            "column_key": "wt30.staff_classification",
            "column_name": "staff_classification",
            "workspace_table_id": 30,
        }
    ]

    compact = DomainSelectionService.compact_capabilities_for_llm(
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
        prompt="Who is the principal at Rossview Elementary",
    )

    filter_keys = [row["column_key"] for row in compact["filter_columns"]]
    assert "wt30.position_title" in filter_keys
    assert "wt30.staff_classification" not in filter_keys


def test_compact_capabilities_projection_policy_debug_exposes_staff_role_rule() -> None:
    capabilities = {
        "domain_id": 5,
        "domain_version": 1,
        "dimensions": [
            {
                "column_key": "wt30.staff_classification",
                "column_name": "staff_classification",
                "semantic_concept_key": "STAFF_CLASSIFICATION",
                "filterable": True,
                "workspace_table_id": 30,
            },
            {
                "column_key": "wt30.position_title",
                "column_name": "position_title",
                "semantic_concept_key": "STAFF_ROLE",
                "filterable": True,
                "workspace_table_id": 30,
            },
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }

    compact = DomainSelectionService.compact_capabilities_for_llm(
        capabilities=capabilities,
        shortlisted_columns=[],
        prompt="Who is the principal at Rossview Elementary",
        include_projection_policy_debug=True,
    )

    assert "human_staff_role_filter_projection" in compact["projection_policy_debug"]["matched_policies"]
    assert "STAFF_ROLE" in compact["projection_policy_debug"]["required_concept_keys"]
    assert "STAFF_CLASSIFICATION" in compact["projection_policy_debug"]["excluded_concept_keys"]


def test_compact_capabilities_explicit_staff_classification_request_keeps_classification() -> None:
    capabilities = {
        "domain_id": 5,
        "domain_version": 1,
        "dimensions": [
            {
                "column_key": "wt30.staff_classification",
                "column_name": "staff_classification",
                "semantic_concept_key": "STAFF_CLASSIFICATION",
                "filterable": True,
                "workspace_table_id": 30,
            },
            {
                "column_key": "wt30.position_title",
                "column_name": "position_title",
                "semantic_concept_key": "STAFF_ROLE",
                "filterable": True,
                "workspace_table_id": 30,
            },
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }
    shortlisted = [
        {
            "column_key": "wt30.staff_classification",
            "column_name": "staff_classification",
            "workspace_table_id": 30,
        }
    ]

    compact = DomainSelectionService.compact_capabilities_for_llm(
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
        prompt="Show me the staff classification at Rossview Elementary",
    )

    filter_keys = [row["column_key"] for row in compact["filter_columns"]]
    assert "wt30.staff_classification" in filter_keys


def test_compact_capabilities_person_lookup_prefers_canonical_name_columns_over_preferred() -> None:
    _ = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )

    capabilities = {
        "domain_id": 5,
        "domain_version": 1,
        "dimensions": [
            {
                "column_key": "wt23.preferred_first_name",
                "column_name": "preferred_first_name",
                "filterable": True,
                "workspace_table_id": 23,
            },
            {
                "column_key": "wt23.preferred_last_name",
                "column_name": "preferred_last_name",
                "filterable": True,
                "workspace_table_id": 23,
            },
            {
                "column_key": "wt23.first_name",
                "column_name": "first_name",
                "filterable": True,
                "workspace_table_id": 23,
            },
            {
                "column_key": "wt23.last_name",
                "column_name": "last_name",
                "filterable": True,
                "workspace_table_id": 23,
            },
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }
    shortlisted = [
        {
            "column_key": "wt23.preferred_first_name",
            "column_name": "preferred_first_name",
            "workspace_table_id": 23,
        },
        {
            "column_key": "wt23.preferred_last_name",
            "column_name": "preferred_last_name",
            "workspace_table_id": 23,
        },
    ]

    compact = DomainSelectionService.compact_capabilities_for_llm(
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
        prompt="Show me where Jennifer Gilstrap works",
    )

    dim_keys = [row["column_key"] for row in compact["dimensions"]]
    filter_keys = [row["column_key"] for row in compact["filter_columns"]]
    assert "wt23.first_name" in dim_keys
    assert "wt23.last_name" in dim_keys
    assert "wt23.preferred_first_name" not in dim_keys
    assert "wt23.preferred_last_name" not in dim_keys
    assert "wt23.first_name" in filter_keys
    assert "wt23.last_name" in filter_keys
    assert "wt23.preferred_first_name" not in filter_keys
    assert "wt23.preferred_last_name" not in filter_keys


def test_compact_capabilities_explicit_preferred_name_request_keeps_preferred_name_columns() -> None:
    _ = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )

    capabilities = {
        "domain_id": 5,
        "domain_version": 1,
        "dimensions": [
            {
                "column_key": "wt23.preferred_first_name",
                "column_name": "preferred_first_name",
                "filterable": True,
                "workspace_table_id": 23,
            },
            {
                "column_key": "wt23.preferred_last_name",
                "column_name": "preferred_last_name",
                "filterable": True,
                "workspace_table_id": 23,
            },
            {
                "column_key": "wt23.first_name",
                "column_name": "first_name",
                "filterable": True,
                "workspace_table_id": 23,
            },
            {
                "column_key": "wt23.last_name",
                "column_name": "last_name",
                "filterable": True,
                "workspace_table_id": 23,
            },
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }
    shortlisted = [
        {
            "column_key": "wt23.preferred_first_name",
            "column_name": "preferred_first_name",
            "workspace_table_id": 23,
        },
        {
            "column_key": "wt23.preferred_last_name",
            "column_name": "preferred_last_name",
            "workspace_table_id": 23,
        },
    ]

    compact = DomainSelectionService.compact_capabilities_for_llm(
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
        prompt="Show me Jennifer Gilstrap preferred name",
    )

    dim_keys = [row["column_key"] for row in compact["dimensions"]]
    assert "wt23.preferred_first_name" in dim_keys
    assert "wt23.preferred_last_name" in dim_keys


def test_score_domain_candidate_prefers_staff_columns_for_work_prompt() -> None:
    _ = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )
    candidate = {"score": 0.5}
    capabilities = {
        "dimensions": [{"column_key": "wt23.staff_unique_id"}] * 20,
    }
    staff_shortlist = [
        {"column_name": "staff_unique_id"},
        {"column_name": "local_staff_id"},
        {"column_name": "position_title"},
        {"column_name": "email_address"},
        {"column_name": "school_name"},
    ]
    student_shortlist = [
        {"column_name": "student_unique_id"},
        {"column_name": "first_name"},
        {"column_name": "last_name"},
        {"column_name": "birth_country"},
        {"column_name": "school_name"},
    ]

    staff_score = DomainSelectionService._score_domain_candidate(
        prompt="Show me where Jennifer Gilstrap works",
        candidate=candidate,
        capabilities=capabilities,
        shortlisted_columns=staff_shortlist,
    )
    student_score = DomainSelectionService._score_domain_candidate(
        prompt="Show me where Jennifer Gilstrap works",
        candidate=candidate,
        capabilities=capabilities,
        shortlisted_columns=student_shortlist,
    )

    assert staff_score > student_score


def test_score_domain_candidate_work_prompt_penalizes_discipline_domain_name() -> None:
    _ = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )
    capabilities = {
        "dimensions": [{"column_key": "wt23.staff_unique_id"}] * 20,
    }
    shortlist = [
        {"column_name": "staff_unique_id"},
        {"column_name": "local_staff_id"},
        {"column_name": "position_title"},
        {"column_name": "email_address"},
        {"column_name": "school_name"},
    ]

    staff_candidate = {"score": 0.5, "name": "Staff & Assignments"}
    discipline_candidate = {"score": 0.5, "name": "Discipline"}

    staff_score = DomainSelectionService._score_domain_candidate(
        prompt="Show me where Jennifer Gilstrap works",
        candidate=staff_candidate,
        capabilities=capabilities,
        shortlisted_columns=shortlist,
    )
    discipline_score = DomainSelectionService._score_domain_candidate(
        prompt="Show me where Jennifer Gilstrap works",
        candidate=discipline_candidate,
        capabilities=capabilities,
        shortlisted_columns=shortlist,
    )

    assert staff_score > discipline_score


def test_score_domain_candidate_work_prompt_penalizes_student_domain_name() -> None:
    _ = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )
    capabilities = {
        "dimensions": [{"column_key": "wt23.staff_unique_id"}] * 20,
    }
    shortlist = [
        {"column_name": "staff_unique_id"},
        {"column_name": "local_staff_id"},
        {"column_name": "position_title"},
        {"column_name": "email_address"},
        {"column_name": "school_name"},
    ]

    staff_candidate = {"score": 0.5, "name": "Staff & Assignments"}
    student_candidate = {"score": 0.5, "name": "Students – Profile & Demographics"}

    staff_score = DomainSelectionService._score_domain_candidate(
        prompt="Show me where Jennifer Gilstrap works",
        candidate=staff_candidate,
        capabilities=capabilities,
        shortlisted_columns=shortlist,
    )
    student_score = DomainSelectionService._score_domain_candidate(
        prompt="Show me where Jennifer Gilstrap works",
        candidate=student_candidate,
        capabilities=capabilities,
        shortlisted_columns=shortlist,
    )

    assert staff_score > student_score


def test_score_domain_candidate_prefers_adm_columns_for_adm_prompt() -> None:
    _ = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )
    candidate = {"score": 0.5}
    capabilities = {
        "dimensions": [{"column_key": "wt31.normalized_adm"}] * 20,
        "domain_metrics": [{"metric_key": "adm_total", "label": "Total ADM"}],
    }
    adm_shortlist = [
        {"column_name": "normalized_adm"},
        {"column_name": "report_period"},
        {"column_name": "school_year"},
        {"column_name": "grade_level_adm"},
        {"column_name": "is_primary_school"},
    ]
    calendar_shortlist = [
        {"column_name": "calendar_date"},
        {"column_name": "term_name"},
        {"column_name": "semester"},
        {"column_name": "month_name"},
        {"column_name": "school_calendar_name"},
    ]

    adm_score = DomainSelectionService._score_domain_candidate(
        prompt="Show base ADM by report period for school year 2026",
        candidate=candidate,
        capabilities=capabilities,
        shortlisted_columns=adm_shortlist,
    )
    calendar_score = DomainSelectionService._score_domain_candidate(
        prompt="Show base ADM by report period for school year 2026",
        candidate=candidate,
        capabilities={"dimensions": [{"column_key": "wt40.calendar_date"}] * 20, "domain_metrics": []},
        shortlisted_columns=calendar_shortlist,
    )

    assert adm_score > calendar_score


def test_score_domain_candidate_adm_prompt_penalizes_calendar_domain_name() -> None:
    _ = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )
    capabilities = {
        "dimensions": [{"column_key": "wt31.normalized_adm"}] * 20,
        "domain_metrics": [{"metric_key": "adm_total", "label": "Total ADM"}],
    }
    shortlist = [
        {"column_name": "normalized_adm"},
        {"column_name": "report_period"},
        {"column_name": "school_year"},
        {"column_name": "is_primary_school"},
    ]

    adm_candidate = {"score": 0.5, "name": "ADM & Enrollment"}
    calendar_candidate = {"score": 0.5, "name": "Academic Calendar & Terms"}

    adm_score = DomainSelectionService._score_domain_candidate(
        prompt="Show base ADM by report period for school year 2026",
        candidate=adm_candidate,
        capabilities=capabilities,
        shortlisted_columns=shortlist,
    )
    calendar_score = DomainSelectionService._score_domain_candidate(
        prompt="Show base ADM by report period for school year 2026",
        candidate=calendar_candidate,
        capabilities=capabilities,
        shortlisted_columns=shortlist,
    )

    assert adm_score > calendar_score


def test_score_domain_candidate_days_off_prompt_prefers_calendar_domain() -> None:
    _ = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )
    candidate = {"score": 0.45, "name": "Academic Calendar And Scheduling"}
    non_calendar_candidate = {"score": 0.45, "name": "Students: Demographics And Groupings"}

    calendar_score = DomainSelectionService._score_domain_candidate(
        prompt="Show me all the days off barksdale elementary has in December",
        candidate=candidate,
        capabilities={"dimensions": [{"column_key": "wt594.calendar_date"}] * 20, "domain_metrics": []},
        shortlisted_columns=[
            {"column_name": "calendar_date"},
            {"column_name": "is_school_day"},
            {"column_name": "school_name"},
            {"column_name": "non_instructional_reason"},
            {"column_name": "holiday_name"},
        ],
    )
    non_calendar_score = DomainSelectionService._score_domain_candidate(
        prompt="Show me all the days off barksdale elementary has in December",
        candidate=non_calendar_candidate,
        capabilities={"dimensions": [{"column_key": "wt552.school_name"}] * 20, "domain_metrics": []},
        shortlisted_columns=[
            {"column_name": "school_name"},
            {"column_name": "entry_date"},
            {"column_name": "exit_withdraw_date"},
            {"column_name": "is_active_enrollment"},
            {"column_name": "school_year"},
        ],
    )

    assert calendar_score > non_calendar_score


def test_score_domain_candidate_age_extreme_prompt_prefers_demographics_domain() -> None:
    _ = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )
    demographics_candidate = {"score": 0.56, "name": "Student Demographics And Enrollment"}
    programs_candidate = {"score": 0.568, "name": "Student Programs And Services"}

    demographics_score = DomainSelectionService._score_domain_candidate(
        prompt="Show me the eldest student",
        candidate=demographics_candidate,
        capabilities={"dimensions": [{"column_key": "wt552.birth_date"}] * 20, "domain_metrics": []},
        shortlisted_columns=[
            {"column_name": "birth_date"},
            {"column_name": "first_name"},
            {"column_name": "last_name"},
            {"column_name": "student_unique_id"},
            {"column_name": "school_name"},
        ],
    )
    programs_score = DomainSelectionService._score_domain_candidate(
        prompt="Show me the eldest student",
        candidate=programs_candidate,
        capabilities={"dimensions": [{"column_key": "wt590.k_student_xyear"}] * 20, "domain_metrics": []},
        shortlisted_columns=[
            {"column_name": "k_student_xyear"},
            {"column_name": "k_student"},
            {"column_name": "program_enroll_begin_date"},
            {"column_name": "program_enroll_end_date"},
            {"column_name": "school_year"},
        ],
    )

    assert demographics_score > programs_score


def test_score_domain_candidate_birth_month_prompt_prefers_demographics_domain() -> None:
    _ = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )
    demographics_candidate = {"score": 0.56, "name": "Student Demographics And Enrollment"}
    programs_candidate = {"score": 0.568, "name": "Student Programs And Services"}

    demographics_score = DomainSelectionService._score_domain_candidate(
        prompt="Show me all the students who have a birthday in March",
        candidate=demographics_candidate,
        capabilities={"dimensions": [{"column_key": "wt552.birth_date"}] * 20, "domain_metrics": []},
        shortlisted_columns=[
            {"column_name": "birth_date"},
            {"column_name": "first_name"},
            {"column_name": "last_name"},
            {"column_name": "student_unique_id"},
            {"column_name": "school_name"},
        ],
    )
    programs_score = DomainSelectionService._score_domain_candidate(
        prompt="Show me all the students who have a birthday in March",
        candidate=programs_candidate,
        capabilities={"dimensions": [{"column_key": "wt590.k_student_xyear"}] * 20, "domain_metrics": []},
        shortlisted_columns=[
            {"column_name": "k_student_xyear"},
            {"column_name": "k_student"},
            {"column_name": "program_enroll_begin_date"},
            {"column_name": "program_enroll_end_date"},
            {"column_name": "school_year"},
        ],
    )

    assert demographics_score > programs_score


def test_get_domain_candidates_expands_work_prompt_and_includes_staff_domain() -> None:
    class _CapturingDomainVector:
        def __init__(self) -> None:
            self.queries = []
            self.calls = []

        def search_domains(self, **kwargs):
            self.calls.append(dict(kwargs))
            query = str(kwargs.get("query") or "")
            self.queries.append(query)
            if "staff assignments" in query.lower():
                return {"results": [{"domain_id": 5, "name": "Staff & Assignments", "score": 0.94}]}
            return {"results": [{"domain_id": 6, "name": "Students – Profile & Demographics", "score": 0.9}]}

    vector = _CapturingDomainVector()
    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=vector,
        llm_client=_FakeLLM(),
    )

    out = svc._domain_selection._get_domain_candidates(
        workspace_id="ws-1",
        prompt="Show me where Jennifer Gilstrap works",
        provided_domain_id=None,
    )

    assert len(vector.queries) > 1
    assert all("vertical_norm" not in call for call in vector.calls)
    assert any("staff assignments" in query.lower() for query in vector.queries)
    assert out[0]["domain_id"] == 5
    assert any(int(row.get("domain_id") or 0) == 6 for row in out)


def test_get_domain_candidates_expands_adm_prompt_and_includes_adm_domain() -> None:
    class _CapturingDomainVector:
        def __init__(self) -> None:
            self.queries = []

        def search_domains(self, **kwargs):
            query = str(kwargs.get("query") or "")
            self.queries.append(query)
            if "average daily membership" in query.lower() or "base adm" in query.lower():
                return {"results": [{"domain_id": 9, "name": "ADM & Membership", "score": 0.94}]}
            return {"results": [{"domain_id": 4, "name": "Academic Calendar & Time", "score": 0.9}]}

    vector = _CapturingDomainVector()
    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=vector,
        llm_client=_FakeLLM(),
    )

    out = svc._domain_selection._get_domain_candidates(
        workspace_id="ws-1",
        prompt="Show base ADM by report period for school year 2026",
        provided_domain_id=None,
    )

    assert len(vector.queries) > 1
    assert any("average daily membership" in query.lower() for query in vector.queries)
    assert out[0]["domain_id"] == 9
    assert any(int(row.get("domain_id") or 0) == 4 for row in out)


def test_get_domain_candidates_uses_semantic_alias_queries_to_improve_recall(monkeypatch) -> None:
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)

    class _SemanticRecallDomainVector:
        def __init__(self) -> None:
            self.queries = []

        def search_domains(self, **kwargs):
            query = str(kwargs.get("query") or "")
            self.queries.append(query)
            query_l = query.lower()
            if "united states" in query_l:
                return {"results": [{"domain_id": 6, "name": "Students – Profile & Demographics", "score": 0.88}]}
            if "nativity" in query_l or "birth country" in query_l:
                return {"results": [{"domain_id": 6, "name": "Students – Profile & Demographics", "score": 0.9}]}
            return {"results": [{"domain_id": 4, "name": "Academic Calendar & Time", "score": 0.91}]}

    vector = _SemanticRecallDomainVector()
    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=vector,
        llm_client=_FakeLLM(),
        value_alias_resolver=_FakeValueAliasResolver(
            [{"concept_key": "COUNTRY", "canonical_value": "United States", "matched_alias": "US"}]
        ),
    )

    out = svc._domain_selection._get_domain_candidates(
        workspace_id="ws-1",
        prompt="Show students not born in the US",
        provided_domain_id=None,
    )

    assert any("United States" in query for query in vector.queries)
    assert any("nativity" in query.lower() for query in vector.queries)
    assert out[0]["domain_id"] == 6
    assert out[0]["source"] == "semantic_vector"
    assert any("semantic_alias:COUNTRY" == reason for reason in list(out[0].get("reason") or []))
    debug_rows = _serialize_domain_candidates_for_debug(out)
    assert debug_rows[0]["semantic_recall"] is True
    assert debug_rows[0]["recall_mode"] == "semantic"
    assert "semantic_alias:COUNTRY" in debug_rows[0]["semantic_reasons"]


def test_score_semantic_grounding_bundle_prefers_richer_semantic_signal() -> None:
    _ = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )

    empty_score = DomainSelectionService._score_semantic_grounding_bundle(
        prompt="Show students by county",
        grounding_bundle=SemanticGroundingBundle(),
    )
    alias_only_score = DomainSelectionService._score_semantic_grounding_bundle(
        prompt="Show students in the US",
        grounding_bundle=SemanticGroundingBundle(alias_constraints=[{"value_hint": "United States"}]),
    )
    rich_score = DomainSelectionService._score_semantic_grounding_bundle(
        prompt="Show staff count by school last year",
        grounding_bundle=_RankingSemanticGroundingService().build_grounding_bundle(base_domain_id=5),
    )

    assert empty_score == 0.0
    assert alias_only_score == 0.02
    assert rich_score > alias_only_score
    assert rich_score <= 0.22


def test_select_domain_and_shortlist_columns_uses_semantic_reranking_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)

    class _DualCapabilitiesService:
        def get_domain_capabilities(self, *, workspace_id, user_id, domain_id):
            del workspace_id, user_id
            if domain_id == 5:
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
                        }
                    ],
                    "domain_metrics": [{"metric_key": "staff_count", "label": "Staff Count", "kind": "count", "agg": "count"}],
                    "user_metrics": [],
                    "overlay_metrics": [],
                    "time_columns": [],
                }
            if domain_id == 6:
                return {
                    "domain_id": 6,
                    "domain_version": 1,
                    "dimensions": [
                        {
                            "column_key": "wt24.student_unique_id",
                            "label": "Student",
                            "data_type": "string",
                            "filterable": True,
                            "workspace_table_id": 24,
                            "model_column_id": 100,
                            "column_name": "student_unique_id",
                        }
                    ],
                    "domain_metrics": [{"metric_key": "student_count", "label": "Student Count", "kind": "count", "agg": "count"}],
                    "user_metrics": [],
                    "overlay_metrics": [],
                    "time_columns": [],
                }
            raise AssertionError(f"unexpected domain_id={domain_id}")

    grounding = _RankingSemanticGroundingService()
    svc = PlannerDomainService(
        capabilities_service=_DualCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
        semantic_grounding_service=grounding,
    )

    monkeypatch.setattr(
        DomainSelectionService,
        "_shortlist_columns_for_domain",
        lambda self, *, prompt, workspace_id, capabilities: list(capabilities.get("dimensions") or []),
    )
    monkeypatch.setattr(
        DomainSelectionService,
        "_score_domain_candidate",
        lambda *args, **kwargs: 0.5,
    )

    selected_domain_id, _capabilities, shortlisted_columns, ranking, rerank_signals = svc._domain_selection._select_domain_and_shortlist_columns(
        workspace_id="ws-1",
        user_id="user-1",
        prompt="Show staff count by school",
        domain_candidates=[
            {"domain_id": 6, "name": "Students", "score": 0.8},
            {"domain_id": 5, "name": "Staff & Assignments", "score": 0.8},
        ],
    )

    assert selected_domain_id == 5
    assert "aggregate_intent" in rerank_signals
    assert "grouped_aggregate" in rerank_signals
    assert "school_aggregate" in rerank_signals
    assert "staff_listing" in rerank_signals
    assert shortlisted_columns[0]["column_key"] == "wt20.school_name"
    ranking_by_domain = {int(row["domain_id"]): row for row in ranking}
    assert ranking_by_domain[5]["semantic_score"] > ranking_by_domain[6]["semantic_score"]
    assert grounding.calls and {int(call["base_domain_id"]) for call in grounding.calls} == {5, 6}


def test_semantic_value_alias_constraints_feature_flag_off(monkeypatch) -> None:
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", False)
    monkeypatch.setattr(semantic_integration_module, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", False)
    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
        value_alias_resolver=_FakeValueAliasResolver(
            [{"concept_key": "COUNTRY", "canonical_value": "United States", "matched_alias": "US"}]
        ),
    )

    constraints = svc._semantic_integration.resolve_alias_constraints(  # noqa: SLF001
        prompt="Show students not born in the US",
    )
    assert constraints == []


def test_rerank_policies_prefer_enrollment_domain_for_school_enrollment_listing(monkeypatch) -> None:
    class _SchoolEnrollmentCapabilitiesService:
        def get_domain_capabilities(self, *, workspace_id, user_id, domain_id):
            del workspace_id, user_id
            if domain_id == 9:
                return {
                    "domain_id": 9,
                    "domain_version": 1,
                    "dimensions": [
                        {"column_key": "wt552.school_name", "column_name": "school_name", "semantic_type": "attribute.school.name"},
                        {"column_key": "wt556.first_name", "column_name": "first_name"},
                        {"column_key": "wt556.last_name", "column_name": "last_name"},
                        {"column_key": "wt570.is_enrolled", "column_name": "is_enrolled"},
                    ],
                    "domain_metrics": [],
                    "user_metrics": [],
                    "overlay_metrics": [],
                    "time_columns": [],
                }
            if domain_id == 15:
                return {
                    "domain_id": 15,
                    "domain_version": 1,
                    "dimensions": [
                        {"column_key": "wt590.k_student_xyear", "column_name": "k_student_xyear"},
                        {"column_key": "wt590.program_enroll_begin_date", "column_name": "program_enroll_begin_date"},
                    ],
                    "domain_metrics": [],
                    "user_metrics": [],
                    "overlay_metrics": [],
                    "time_columns": [],
                }
            raise AssertionError(f"unexpected domain_id={domain_id}")

    svc = PlannerDomainService(
        capabilities_service=_SchoolEnrollmentCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
        planner_rerank_policy_service=_FakePlannerRerankPolicyService(
            [
                {
                    "policy_key": "student_listing_school_literal",
                    "scope_type": "global",
                    "priority": 100,
                    "stop_on_match": 0,
                    "policy_json": {
                        "version": 1,
                        "when_signals_all": ["student_listing", "school_literal_present"],
                        "prefer_capabilities": ["SCHOOL_NAME", "STUDENT_IDENTITY"],
                        "penalize_missing": ["SCHOOL_NAME"],
                        "require_for_bonus": ["STUDENT_IDENTITY"],
                        "boost": 0.2,
                        "penalty": 0.3,
                        "max_effect": 0.3,
                    },
                },
                {
                    "policy_key": "student_listing_enrollment_status",
                    "scope_type": "global",
                    "priority": 110,
                    "stop_on_match": 0,
                    "policy_json": {
                        "version": 1,
                        "when_signals_all": ["student_listing", "status_enrolled"],
                        "prefer_capabilities": ["ENROLLMENT_STATUS"],
                        "penalize_missing": ["ENROLLMENT_STATUS"],
                        "require_for_bonus": ["ENROLLMENT_STATUS"],
                        "boost": 0.15,
                        "penalty": 0.2,
                        "max_effect": 0.2,
                    },
                },
            ]
        ),
    )

    monkeypatch.setattr(
        DomainSelectionService,
        "_shortlist_columns_for_domain",
        lambda self, *, prompt, workspace_id, capabilities: list(capabilities.get("dimensions") or []),
    )
    monkeypatch.setattr(
        DomainSelectionService,
        "_score_domain_candidate",
        lambda *args, **kwargs: 0.94266
        if int(kwargs.get("candidate", {}).get("domain_id", 0)) == 9
        else 1.0242,
    )

    selected_domain_id, _capabilities, _shortlisted_columns, ranking, rerank_signals = svc._domain_selection._select_domain_and_shortlist_columns(
        workspace_id="ws-1",
        user_id="user-1",
        prompt="Show me all the students enrolled at Barksdale Elementary",
        domain_candidates=[
            {"domain_id": 9, "name": "Student Enrollment And Attendance", "score": 0.5964},
            {"domain_id": 15, "name": "Student Programs And Services", "score": 0.568},
        ],
    )

    ranking_by_domain = {int(row["domain_id"]): row for row in ranking}
    assert selected_domain_id == 9
    assert "school_literal_present" in rerank_signals
    assert "status_enrolled" in rerank_signals
    assert ranking_by_domain[9]["policy_adjustment"] > 0
    assert ranking_by_domain[15]["policy_adjustment"] < 0
    assert ranking_by_domain[9]["score"] > ranking_by_domain[15]["score"]
    assert ranking_by_domain[9]["domain_capabilities"]["present"] == [
        "ENROLLMENT_STATUS",
        "SCHOOL_NAME",
        "STUDENT_IDENTITY",
    ]


def test_semantic_value_alias_constraints_feature_flag_on_merges_into_slot_hints(monkeypatch) -> None:
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)
    monkeypatch.setattr(semantic_integration_module, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)
    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
        value_alias_resolver=_FakeValueAliasResolver(
            [{"concept_key": "COUNTRY", "canonical_value": "United States", "matched_alias": "US"}]
        ),
    )

    constraints = svc._semantic_integration.resolve_alias_constraints(  # noqa: SLF001
        prompt="Show students not born in the US",
    )
    assert constraints and constraints[0]["value_hint"] == "United States"

    merged = svc._llm_planning._merge_slot_hints(
        prompt="Show students not born in the US",
        slot_payload={"intent": "list", "entity": "students", "constraints": [], "time_phrases": []},
        semantic_constraints=constraints,
    )
    assert any(str(item.get("value_hint") or "") == "United States" for item in merged["constraints"])
    assert "United States" in merged["subgroups"]


def test_semantic_value_alias_constraints_feature_flag_on_is_resilient_to_errors(monkeypatch) -> None:
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)
    monkeypatch.setattr(semantic_integration_module, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)
    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
        value_alias_resolver=_FakeValueAliasResolver(should_raise=True),
    )

    constraints = svc._semantic_integration.resolve_alias_constraints(  # noqa: SLF001
        prompt="Show students not born in the US",
    )
    assert constraints == []


def test_plan_debug_includes_semantic_grounding_bundle_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)
    grounding = _FakeSemanticGroundingService()
    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
        semantic_grounding_service=grounding,
    )

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "base_domain_id": 6,
            "prompt": "students per teacher by county",
            "debug": True,
        },
        user_id="user-1",
    )

    debug = out["debug"]
    assert debug["semantic_grounding"]["alias_constraints"][0]["value_hint"] == "United States"
    assert "projection_policy" in debug
    assert isinstance(debug["projection_policy"]["matched_policies"], list)
    assert isinstance(debug["projection_policy"]["prompt_signals"], list)
    assert grounding.calls
    assert grounding.calls[0]["base_domain_id"] == 6
    assert grounding.calls[0]["workspace_id"] == "ws-1"


def test_plan_normalizes_semantic_value_aliases_in_fallback_path(monkeypatch) -> None:
    class _RaceCapsService:
        def get_domain_capabilities(self, *, workspace_id, user_id, domain_id):
            del workspace_id, user_id
            assert domain_id == 6
            return {
                "domain_id": 6,
                "domain_version": 1,
                "dimensions": [
                    {
                        "column_key": "wt24.student_unique_id",
                        "label": "Student Id",
                        "data_type": "string",
                        "filterable": True,
                        "workspace_table_id": 24,
                        "workspace_column_id": 1001,
                        "model_column_id": 1001,
                        "column_name": "student_unique_id",
                    },
                    {
                        "column_key": "wt24.first_name",
                        "label": "First Name",
                        "data_type": "string",
                        "filterable": True,
                        "workspace_table_id": 24,
                        "workspace_column_id": 1002,
                        "model_column_id": 1002,
                        "column_name": "first_name",
                    },
                    {
                        "column_key": "wt24.last_name",
                        "label": "Last Name",
                        "data_type": "string",
                        "filterable": True,
                        "workspace_table_id": 24,
                        "workspace_column_id": 1003,
                        "model_column_id": 1003,
                        "column_name": "last_name",
                    },
                    {
                        "column_key": "wt24.race_ethnicity",
                        "label": "Race Ethnicity",
                        "data_type": "string",
                        "filterable": True,
                        "workspace_table_id": 24,
                        "workspace_column_id": 1004,
                        "model_column_id": 1004,
                        "column_name": "race_ethnicity",
                    },
                    {
                        "column_key": "wt24.is_enrolled",
                        "label": "Is Enrolled",
                        "data_type": "int",
                        "filterable": True,
                        "workspace_table_id": 24,
                        "workspace_column_id": 1005,
                        "model_column_id": 1005,
                        "column_name": "is_enrolled",
                    },
                ],
                "domain_metrics": [],
                "user_metrics": [],
                "overlay_metrics": [],
                "time_columns": [],
            }

    class _RaceAliasFallbackLLM:
        def chat_json_with_trace(self, **kwargs):
            user_prompt = str(kwargs.get("user_prompt") or "")
            if "Task: Extract lightweight planning slots" in user_prompt:
                return {
                    "parsed": {
                        "intent": "list",
                        "entity": "students",
                        "constraints": [],
                        "time_phrases": [],
                    },
                    "content": "{}",
                    "raw_text": "{}",
                }
            return {
                "parsed": {
                    "intent": "list",
                    "selects": {
                        "dimensions": [
                            {"column_key": "wt24.student_unique_id"},
                            {"column_key": "wt24.first_name"},
                            {"column_key": "wt24.last_name"},
                        ],
                        "metrics": [],
                    },
                    "filters": [
                        {"column_key": "wt24.race_ethnicity", "op": "=", "value": "African American"},
                        {"column_key": "wt24.is_enrolled", "op": "=", "value": 1},
                    ],
                    "time": {},
                    "grouping": {
                        "group_by": ["wt24.student_unique_id", "wt24.first_name", "wt24.last_name"],
                        "order_by": [],
                        "limit": None,
                    },
                },
                "content": "{}",
                "raw_text": "{}",
            }

    class _FakeSql:
        def execute_query_mappings(self, query, params):
            del params
            if "FROM semantic_column_map scm" in query:
                return []
            if "FROM workspace_column_semantic_concept_map m" in query:
                return [{"workspace_column_id": 1004, "concept_key": "RACE_ETHNICITY"}]
            if "FROM semantic_value_alias va" in query:
                return [
                    {
                        "concept_key": "RACE_ETHNICITY",
                        "alias_value": "african american",
                        "canonical_value": "Black",
                    }
                ]
            return []

    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_COMPACT_PLANNER_ENABLED", False)
    monkeypatch.setattr(planner_domain_service_module, "ForgeMetaSQL", lambda: _FakeSql())
    monkeypatch.setattr(semantic_integration_module, "ForgeMetaSQL", lambda: _FakeSql())

    svc = PlannerDomainService(
        capabilities_service=_RaceCapsService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_RaceAliasFallbackLLM(),
    )

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "generic",
            "base_domain_id": 6,
            "prompt": "Show me all the african american students currently enrolled",
            "debug": True,
        },
        user_id="user-1",
    )

    filters = out["plan_json_v2"]["filters"]
    assert out["validation"]["is_valid"] is True
    assert filters[0]["column_key"] == "wt24.race_ethnicity"
    assert filters[0]["value"] == "Black"
    assert out["sql_json"]["filters"]["children"][0]["value"] == "Black"
    assert out["debug"]["semantic_value_alias_normalization"]["applied"] == 1
    assert out["debug"]["semantic_value_alias_normalization"]["changes"][0]["concept_key"] == "RACE_ETHNICITY"


def test_semester_indicator_resolution_uses_explicit_semantic_concept_keys(monkeypatch) -> None:
    class _FakeSql:
        def execute_query_mappings(self, query, params):
            del params
            if "FROM workspace_column wc" in query:
                return [
                    {"workspace_column_id": 9001, "concept_key": "SEMESTER_SPRING_FLAG"},
                    {"workspace_column_id": 9002, "concept_key": "SEMESTER_FALL_FLAG"},
                    {"workspace_column_id": 9003, "concept_key": "SEMESTER_YEAR_ROUND_FLAG"},
                ]
            if "FROM workspace_column_semantic_concept_map m" in query:
                return []
            return []

    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)
    monkeypatch.setattr(planner_domain_service_module, "ForgeMetaSQL", lambda: _FakeSql())
    monkeypatch.setattr(semantic_integration_module, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)
    monkeypatch.setattr(semantic_integration_module, "ForgeMetaSQL", lambda: _FakeSql())

    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )
    capabilities = {
        "dimensions": [],
        "filter_columns": [
            {
                "column_key": "wt24.is_spring_block",
                "filterable": True,
                "column_name": "is_spring_block",
                "model_column_id": 9001,
            },
            {
                "column_key": "wt24.is_fall_block",
                "filterable": True,
                "column_name": "is_fall_block",
                "model_column_id": 9002,
            },
            {
                "column_key": "wt24.is_year_round_block",
                "filterable": True,
                "column_name": "is_year_round_block",
                "model_column_id": 9003,
            },
        ],
        "time_columns": [],
    }

    out = svc._semantic_integration.resolve_semester_indicator_columns(  # noqa: SLF001
        workspace_id="ws-1",
        capabilities=capabilities,
    )
    assert out["spring"] == "wt24.is_spring_block"
    assert out["fall"] == "wt24.is_fall_block"
    assert out["year_round"] == "wt24.is_year_round_block"


def test_semantic_value_alias_normalization_coerces_boolean_flag_values(monkeypatch) -> None:
    class _FakeSql:
        def execute_query_mappings(self, query, params):
            del params
            if "FROM semantic_column_map scm" in query:
                return []
            if "FROM workspace_column_semantic_concept_map m" in query:
                return [{"workspace_column_id": 2002, "concept_key": "IS_SCHOOL_DAY"}]
            if "FROM semantic_value_alias va" in query:
                return [
                    {
                        "concept_key": "IS_SCHOOL_DAY",
                        "alias_value": "off day",
                        "canonical_value": "false",
                    }
                ]
            return []

    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)
    monkeypatch.setattr(planner_domain_service_module, "ForgeMetaSQL", lambda: _FakeSql())
    monkeypatch.setattr(semantic_integration_module, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)
    monkeypatch.setattr(semantic_integration_module, "ForgeMetaSQL", lambda: _FakeSql())

    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
    )

    plan_json = {
        "filters": [
            {"column_key": "wt24.is_school_day", "op": "=", "value": "off day"},
        ]
    }
    capabilities = {
        "dimensions": [],
        "filter_columns": [
            {
                "column_key": "wt24.is_school_day",
                "label": "Is School Day",
                "data_type": "boolean",
                "semantic_type": "flag",
                "filterable": True,
                "workspace_table_id": 24,
                "workspace_column_id": 2002,
                "model_column_id": 2002,
                "column_name": "is_school_day",
            }
        ],
        "time_columns": [],
    }

    normalized_plan, issues, debug = svc._semantic_integration.normalize_semantic_value_alias_filters(  # noqa: SLF001
        plan_json=plan_json,
        workspace_id="ws-1",
        capabilities=capabilities,
    )

    filters = normalized_plan["filters"]
    assert issues == ["semantic_value_alias_normalized:wt24.is_school_day:IS_SCHOOL_DAY"]
    assert filters[0]["column_key"] == "wt24.is_school_day"
    assert filters[0]["value"] is False
    assert debug["applied"] == 1
    assert debug["changes"][0]["concept_key"] == "IS_SCHOOL_DAY"
    assert debug["changes"][0]["coerced_boolean"] is True


def test_validation_uses_full_capabilities_not_compact_subset() -> None:
    class _StudentCapsService:
        def get_domain_capabilities(self, *, workspace_id, user_id, domain_id):
            del workspace_id, user_id
            assert domain_id == 6
            return {
                "domain_id": 6,
                "domain_version": 1,
                "dimensions": [
                    {
                        "column_key": "wt24.student_unique_id",
                        "label": "Student Unique ID",
                        "data_type": "string",
                        "filterable": True,
                        "workspace_table_id": 24,
                        "model_column_id": 1001,
                        "column_name": "student_unique_id",
                    },
                    {
                        "column_key": "wt24.first_name",
                        "label": "First Name",
                        "data_type": "string",
                        "filterable": True,
                        "workspace_table_id": 24,
                        "model_column_id": 1002,
                        "column_name": "first_name",
                    },
                    {
                        "column_key": "wt24.last_name",
                        "label": "Last Name",
                        "data_type": "string",
                        "filterable": True,
                        "workspace_table_id": 24,
                        "model_column_id": 1003,
                        "column_name": "last_name",
                    },
                    {
                        "column_key": "wt24.birth_country",
                        "label": "Birth Country",
                        "data_type": "string",
                        "filterable": True,
                        "workspace_table_id": 24,
                        "model_column_id": 1004,
                        "column_name": "birth_country",
                    },
                ],
                "domain_metrics": [],
                "user_metrics": [],
                "overlay_metrics": [],
                "time_columns": [],
            }

    svc = PlannerDomainService(
        capabilities_service=_StudentCapsService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLMStudentIdentityPlan(),
    )

    # Simulate compact shortlist that omits required identity columns.
    svc._domain_selection.compact_capabilities_for_llm = lambda *args, **kwargs: {  # type: ignore[method-assign]
        "domain_id": 6,
        "domain_version": 1,
        "dimensions": [
            {
                "column_key": "wt24.birth_country",
                "column_name": "birth_country",
                "filterable": True,
                "workspace_table_id": 24,
                "model_column_id": 1004,
            }
        ],
        "time_columns": [],
        "filter_columns": [
            {
                "column_key": "wt24.birth_country",
                "column_name": "birth_country",
                "filterable": True,
                "workspace_table_id": 24,
                "model_column_id": 1004,
            }
        ],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "base_domain_id": 6,
            "prompt": "students not born in the us",
            "debug": True,
        },
        user_id="user-1",
    )

    assert out["validation"]["is_valid"] is True
    assert out["sql_json"]


def test_plan_keeps_first_and_last_name_filters_when_columns_are_filterable() -> None:
    class _NameCapsService:
        def get_domain_capabilities(self, *, workspace_id, user_id, domain_id):
            del workspace_id, user_id
            assert domain_id == 6
            return {
                "domain_id": 6,
                "domain_version": 1,
                "dimensions": [
                    {
                        "column_key": "wt24.k_student",
                        "label": "Student Key",
                        "data_type": "string",
                        "filterable": True,
                        "workspace_table_id": 24,
                        "model_column_id": 348,
                        "column_name": "k_student",
                    },
                    {
                        "column_key": "wt24.first_name",
                        "label": "First Name",
                        "data_type": "string",
                        "filterable": True,
                        "workspace_table_id": 24,
                        "model_column_id": 354,
                        "column_name": "first_name",
                    },
                    {
                        "column_key": "wt24.last_name",
                        "label": "Last Name",
                        "data_type": "string",
                        "filterable": True,
                        "workspace_table_id": 24,
                        "model_column_id": 356,
                        "column_name": "last_name",
                    },
                ],
                "domain_metrics": [],
                "user_metrics": [],
                "overlay_metrics": [],
                "time_columns": [],
            }

    svc = PlannerDomainService(
        capabilities_service=_NameCapsService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLMNameFilters(),
    )
    svc._shortlist_columns_for_domain = lambda **kwargs: [  # type: ignore[method-assign]
        {"column_key": "wt24.k_student", "workspace_table_id": 24, "column_name": "k_student"},
        {"column_key": "wt24.first_name", "workspace_table_id": 24, "column_name": "first_name"},
    ]

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "base_domain_id": 6,
            "prompt": "Find all students with a first name of Holden and last name of Black",
            "debug": True,
        },
        user_id="user-1",
    )

    filters = out["plan_json_v2"]["filters"]
    assert out["validation"]["is_valid"] is True
    assert out["plan_json_v2"]["domain_name"] == "domain_6"
    assert {f["column_key"] for f in filters} == {"wt24.first_name", "wt24.last_name"}
    assert not any(rep == "dropped_invalid_filter:wt24.last_name" for rep in out["validation"]["repairs_applied"])


def test_district_county_retry_hint_triggers_for_county_column_on_district_phrase() -> None:
    capabilities = {
        "dimensions": [
            {"column_key": "wt20.lea_name", "column_name": "lea_name", "filterable": True},
            {"column_key": "wt20.name_of_county", "column_name": "name_of_county", "filterable": True},
        ],
        "filter_columns": [
            {"column_key": "wt20.lea_name", "column_name": "lea_name", "filterable": True},
            {"column_key": "wt20.name_of_county", "column_name": "name_of_county", "filterable": True},
        ],
        "time_columns": [],
    }
    plan = {
        "filters": [
            {
                "column_key": "wt20.name_of_county",
                "op": "eq",
                "value": "Davidson County",
            }
        ]
    }

    hint = _district_county_retry_hint(  # noqa: SLF001
        normalized_prompt="How many student are enrolled in the Davidson County district",
        plan_json=plan,
        capabilities=capabilities,
    )

    assert hint is not None
    assert "district name" in hint.lower() or "district" in hint.lower()


def test_district_county_retry_hint_does_not_trigger_for_geography_prompt() -> None:
    capabilities = {
        "dimensions": [
            {"column_key": "wt20.name_of_county", "column_name": "name_of_county", "filterable": True},
        ],
        "filter_columns": [
            {"column_key": "wt20.name_of_county", "column_name": "name_of_county", "filterable": True},
        ],
        "time_columns": [],
    }
    plan = {
        "filters": [
            {
                "column_key": "wt20.name_of_county",
                "op": "eq",
                "value": "Davidson County",
            }
        ]
    }

    hint = _district_county_retry_hint(  # noqa: SLF001
        normalized_prompt="schools in Davidson County",
        plan_json=plan,
        capabilities=capabilities,
    )

    assert hint is None


def test_normalize_llm_plan_accepts_metric_ref_aliases() -> None:
    out = LLMPlanningService._normalize_llm_plan(
        raw_plan={
            "selects": {
                "dimensions": [{"columnKey": "wt187.territory_name"}],
                "metrics": [{"metricRef": "domain_metric:sales_revenue", "metric_ref": ""}],
            }
        },
        trace_id="t1",
        workspace_id="ws-1",
        base_domain_id=3,
        base_domain_name="Sales Performance",
    )

    assert out["selects"]["dimensions"] == [{"column_key": "wt187.territory_name"}]
    assert out["selects"]["metrics"] == [{"metric_ref": "domain_metric:sales_revenue"}]


def test_normalize_relative_time_last_month_to_custom_calendar_range() -> None:
    plan = {
        "time": {"time_range": "last_30_days"},
        "filters": [
            {"column_key": "wt179.month_num", "op": "=", "value": 11},
            {"column_key": "wt187.region_name", "op": "=", "value": "West"},
        ],
    }
    capabilities = {
        "dimensions": [
            {"column_key": "wt187.region_name", "column_name": "region_name", "data_type": "string"},
        ],
        "filter_columns": [
            {"column_key": "wt179.month_num", "column_name": "month_num", "data_type": "int"},
        ],
        "time_columns": [
            {"column_key": "wt179.date_key", "column_name": "date_key", "data_type": "date"},
        ],
    }

    out, issues, debug = _normalize_relative_time_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        prompt="What were total sales by territory last month?",
        today=date(2026, 3, 10),
    )

    assert issues == []
    assert out["time"]["time_range"] == "custom"
    assert out["time"]["start_date"] == "2026-02-01"
    assert out["time"]["end_date"] == "2026-02-28"
    assert out["time"]["time_column_key"] == "wt179.date_key"
    assert out["filters"] == [{"column_key": "wt187.region_name", "op": "=", "value": "West"}]
    assert debug and debug[0]["action"] == "normalized_relative_time"


def test_normalize_relative_time_this_month_to_custom_calendar_range() -> None:
    plan = {
        "time": {},
        "filters": [
            {"column_key": "wt179.month_num", "op": "=", "value": 10},
            {"column_key": "wt179.year_num", "op": "=", "value": 2023},
        ],
    }
    capabilities = {
        "dimensions": [],
        "filter_columns": [
            {"column_key": "wt179.month_num", "column_name": "month_num", "data_type": "int"},
            {"column_key": "wt179.year_num", "column_name": "year_num", "data_type": "int"},
        ],
        "time_columns": [
            {"column_key": "wt179.date_key", "column_name": "date_key", "data_type": "date"},
        ],
    }

    out, issues, debug = _normalize_relative_time_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        prompt="Show me the top 5 sales reps for this month",
        today=date(2026, 3, 11),
    )

    assert issues == []
    assert out["time"]["time_range"] == "custom"
    assert out["time"]["start_date"] == "2026-03-01"
    assert out["time"]["end_date"] == "2026-03-11"
    assert out["filters"] == []
    assert debug and debug[0]["relative_phrase"] == "this month"


def test_normalize_named_month_to_custom_calendar_range() -> None:
    plan = {"time": {}, "filters": []}
    capabilities = {
        "dimensions": [],
        "filter_columns": [],
        "time_columns": [
            {"column_key": "wt536.calendar_date", "column_name": "calendar_date", "data_type": "date"},
        ],
    }

    out, issues, debug = _normalize_relative_time_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        prompt="Show me all the days off Barksdale Elementary has in December",
        today=date(2026, 3, 25),
    )

    assert issues == []
    assert out["time"]["time_range"] == "custom"
    assert out["time"]["start_date"] == "2026-12-01"
    assert out["time"]["end_date"] == "2026-12-31"
    assert out["time"]["time_column_key"] == "wt536.calendar_date"
    assert debug and debug[0]["action"] == "normalized_named_month_time"
    assert debug[0]["matched_month"] == "december"
    assert debug[0]["matched_year"] == 2026


def test_normalize_named_month_uses_school_year_time_policy() -> None:
    plan = {"time": {}, "filters": []}
    capabilities = {
        "dimensions": [],
        "filter_columns": [],
        "time_columns": [
            {"column_key": "wt536.calendar_date", "column_name": "calendar_date", "data_type": "date"},
        ],
    }

    out, issues, debug = _normalize_relative_time_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        prompt="Show me all the days off Barksdale Elementary has in December",
        domain_time_policy={
            "calendar_mode": "school_year",
            "school_year_start_month": 8,
            "school_year_end_month": 5,
        },
        today=date(2026, 3, 25),
    )

    assert issues == []
    assert out["time"]["time_range"] == "custom"
    assert out["time"]["start_date"] == "2025-12-01"
    assert out["time"]["end_date"] == "2025-12-31"
    assert out["time"]["time_column_key"] == "wt536.calendar_date"
    assert debug and debug[0]["matched_year"] == 2025
    assert debug[0]["school_year_anchored"] is True


def test_normalize_relative_time_skips_named_month_for_birth_month_prompt() -> None:
    plan = {"time": {}, "filters": []}
    capabilities = {
        "dimensions": [
            {"column_key": "wt552.birth_date", "column_name": "birth_date", "data_type": "date"},
        ],
        "filter_columns": [],
        "time_columns": [
            {"column_key": "wt536.calendar_date", "column_name": "calendar_date", "data_type": "date"},
        ],
    }

    out, issues, debug = _normalize_relative_time_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        prompt="Show me all the students who have a birthday in March",
        today=date(2026, 3, 25),
    )

    assert issues == []
    assert out["time"] == {}
    assert debug and debug[0]["reason"] == "birth_month_prompt_uses_date_part"


def test_normalize_relative_time_does_not_rewrite_last_30_days_prompt() -> None:
    plan = {"time": {"time_range": "last_30_days"}, "filters": []}
    capabilities = {
        "dimensions": [],
        "filter_columns": [],
        "time_columns": [
            {"column_key": "wt179.date_key", "column_name": "date_key", "data_type": "date"},
        ],
    }
    out, issues, debug = _normalize_relative_time_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        prompt="Show total sales for the last 30 days",
        today=date(2026, 3, 10),
    )
    assert issues == []
    assert out["time"]["time_range"] == "last_30_days"
    assert "start_date" not in out["time"]
    assert debug == []


def test_normalize_relative_time_this_quarter_with_fiscal_policy() -> None:
    plan = {
        "time": {},
        "filters": [
            {
                "column_key": "wt179.fiscal_quarter",
                "op": "in",
                "value": {"type": "time_period", "time_period": "quarter", "time_range": "this_quarter"},
            }
        ],
    }
    capabilities = {
        "dimensions": [],
        "filter_columns": [
            {"column_key": "wt179.fiscal_quarter", "column_name": "fiscal_quarter", "data_type": "string"},
        ],
        "time_columns": [
            {"column_key": "wt179.date_key", "column_name": "date_key", "data_type": "date"},
        ],
    }
    policy = {
        "calendar_mode": "fiscal",
        "fiscal_year_start_month": 7,
        "relative_map": {},
    }
    out, issues, debug = _normalize_relative_time_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        prompt="Show total sales by rep this quarter",
        domain_time_policy=policy,
        today=date(2026, 3, 11),
    )
    assert issues == []
    assert out["time"]["time_range"] == "custom"
    assert out["time"]["start_date"] == "2026-01-01"
    assert out["time"]["end_date"] == "2026-03-11"
    assert out["time"]["time_grain"] == "quarter"
    assert out["filters"] == []
    assert debug and debug[0]["relative_token"] == "this_quarter"


def test_normalize_relative_time_uses_policy_relative_map_alias() -> None:
    plan = {"time": {}, "filters": []}
    capabilities = {
        "dimensions": [],
        "filter_columns": [],
        "time_columns": [
            {"column_key": "wt179.date_key", "column_name": "date_key", "data_type": "date"},
        ],
    }
    policy = {
        "calendar_mode": "calendar",
        "relative_map": {"this qtr": "this_quarter"},
    }
    out, issues, debug = _normalize_relative_time_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        prompt="Show total sales by territory this qtr",
        domain_time_policy=policy,
        today=date(2026, 3, 10),
    )
    assert issues == []
    assert out["time"]["start_date"] == "2026-01-01"
    assert out["time"]["end_date"] == "2026-03-10"
    assert debug and debug[0]["relative_token"] == "this_quarter"


def test_normalize_relative_time_rewrites_time_period_filter_without_prompt_phrase() -> None:
    plan = {
        "time": {},
        "filters": [
            {
                "column_key": "wt179.fiscal_quarter",
                "op": "in",
                "value": {"type": "time_period", "time_period": "quarter", "time_range": "this_quarter"},
            },
            {"column_key": "wt187.region_name", "op": "=", "value": "West"},
        ],
    }
    capabilities = {
        "dimensions": [
            {"column_key": "wt187.region_name", "column_name": "region_name", "data_type": "string"},
        ],
        "filter_columns": [
            {"column_key": "wt179.fiscal_quarter", "column_name": "fiscal_quarter", "data_type": "string"},
        ],
        "time_columns": [
            {"column_key": "wt179.date_key", "column_name": "date_key", "data_type": "date"},
        ],
    }
    out, issues, _debug = _normalize_relative_time_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        prompt="Show total sales by region",
        domain_time_policy={"relative_map": {}},
        today=date(2026, 3, 10),
    )
    assert issues == []
    assert out["time"]["time_range"] == "custom"
    assert out["time"]["start_date"] == "2026-01-01"
    assert out["time"]["end_date"] == "2026-03-10"
    assert out["filters"] == [{"column_key": "wt187.region_name", "op": "=", "value": "West"}]


def test_prompt_is_followup_edit_does_not_treat_top_query_as_patch() -> None:
    assert _prompt_is_followup_edit(
        prompt="Show me the top 5 sales reps for this month",
        prior_prompt="Show me revenue by territory last month",
    ) is False


def test_normalize_top_bottom_ranking_sets_metric_limit_and_order() -> None:
    plan = {
        "intent": "list",
        "selects": {
            "dimensions": [
                {"column_key": "wt186.first_name"},
                {"column_key": "wt186.last_name"},
                {"column_key": "wt186.sales_rep_id"},
            ],
            "metrics": [],
        },
        "filters": [],
        "time": {},
        "grouping": {"group_by": ["wt186.first_name", "wt186.last_name", "wt186.sales_rep_id"], "order_by": [], "limit": None},
    }
    capabilities = {
        "domain_metrics": [
            {"metric_key": "sales_revenue", "label": "Sales Revenue"},
            {"metric_key": "sales_units", "label": "Sales Units"},
        ],
        "user_metrics": [],
        "overlay_metrics": [],
    }

    out, issues, debug = _normalize_top_bottom_ranking_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        prompt="Show me the top 5 sales reps for this month",
    )

    assert issues == []
    assert out["intent"] == "aggregate"
    assert out["selects"]["metrics"] == [{"metric_ref": "domain_metric:sales_revenue"}]
    assert out["grouping"]["limit"] == 5
    assert out["grouping"]["order_by"] == [{"by": "metric:domain_metric:sales_revenue", "dir": "desc"}]
    assert debug and debug[0]["action"] == "normalized_top_bottom_ranking"


def test_normalize_year_keyword_filters_for_year_num() -> None:
    plan = {
        "filters": [
            {"column_key": "wt179.year_num", "op": "eq", "value": "current_year"},
        ]
    }
    capabilities = {
        "dimensions": [],
        "filter_columns": [
            {"column_key": "wt179.year_num", "column_name": "year_num", "data_type": "int"},
        ],
        "time_columns": [],
    }
    out, issues, debug = _normalize_year_keyword_filters_in_plan(
        plan_json=plan,
        capabilities=capabilities,
        today=date(2026, 3, 10),
    )
    assert issues == []
    assert out["filters"] == [{"column_key": "wt179.year_num", "op": "eq", "value": 2026}]
    assert debug and debug[0]["action"] == "normalized_year_keyword"
