from __future__ import annotations

from app.services.domain.planner_domain_capability_service import PlannerDomainCapabilityService
from app.services.planner_domain.prompt_signal_service import PromptSignalService
from app.services.planner_domain.rerank_policy_engine import PlannerDomainRerankPolicyEngine


class _EmptySQL:
    def execute_query_mappings(self, query, params=None):
        del query, params
        return []


class _FakePolicyService:
    def __init__(self, rows):
        self._rows = list(rows)

    def get_applicable_policies(self, *, workspace_id: str, vertical_norm: str, base_domain_id: int):
        del workspace_id, vertical_norm, base_domain_id
        return list(self._rows)


def test_prompt_signal_service_extracts_school_and_enrollment_signals() -> None:
    svc = PromptSignalService()
    signals = svc.extract_signals(prompt="Show me all the students enrolled at Barksdale Elementary")
    assert "student_listing" in signals
    assert "school_literal_present" in signals
    assert "status_enrolled" in signals
    assert "needs_school_filter" in signals
    assert "needs_enrollment_status" in signals


def test_prompt_signal_service_extracts_month_as_time_constraint() -> None:
    svc = PromptSignalService()
    signals = svc.extract_signals(prompt="How many days off are there in December?")
    assert "time_constraint_present" in signals


def test_prompt_signal_service_extracts_days_off_and_lowercase_school_literal() -> None:
    svc = PromptSignalService()
    signals = svc.extract_signals(prompt="Show me all the days off barksdale elementary has in December")
    assert "calendar_days_off_prompt" in signals
    assert "school_literal_present" in signals
    assert "needs_school_filter" in signals
    assert "time_constraint_present" in signals


def test_prompt_signal_service_extracts_age_extreme_signal() -> None:
    svc = PromptSignalService()
    signals = svc.extract_signals(prompt="Show me the eldest student")
    assert "age_extreme_prompt" in signals
    assert "student_listing" in signals
    assert "needs_student_identity" in signals


def test_prompt_signal_service_extracts_birth_month_signal() -> None:
    svc = PromptSignalService()
    signals = svc.extract_signals(prompt="Show me all the students who have a birthday in March")
    assert "birth_month_prompt" in signals
    assert "time_constraint_present" in signals
    assert "student_listing" in signals


def test_capability_service_prefers_explicit_workspace_scope_over_vertical_scope() -> None:
    class _SQL:
        def execute_query_mappings(self, query, params=None):
            del query, params
            return [
                {
                    "scope_type": "vertical",
                    "scope_workspace_id": None,
                    "scope_vertical_norm": "education",
                    "base_domain_id": 9,
                    "capability_key": "SCHOOL_NAME",
                    "support_level": "partial",
                    "source_type": "semantic_concept",
                    "source_ref": "vertical-row",
                    "confidence": 0.6,
                },
                {
                    "scope_type": "workspace",
                    "scope_workspace_id": "ws-1",
                    "scope_vertical_norm": None,
                    "base_domain_id": 9,
                    "capability_key": "SCHOOL_NAME",
                    "support_level": "direct",
                    "source_type": "semantic_concept",
                    "source_ref": "workspace-row",
                    "confidence": 0.9,
                },
            ]

    svc = PlannerDomainCapabilityService(sql=_SQL())
    out = svc.resolve_capabilities(
        workspace_id="ws-1",
        vertical_norm="education",
        base_domain_id=9,
        capabilities={"dimensions": [], "time_columns": [], "filter_columns": [], "domain_metrics": []},
        shortlisted_columns=[],
    )
    record = next(row for row in out["records"] if row["capability_key"] == "SCHOOL_NAME")
    assert record["scope_type"] == "workspace"
    assert record["source_ref"] == "workspace-row"


def test_capability_service_infers_calendar_capabilities() -> None:
    svc = PlannerDomainCapabilityService(sql=_EmptySQL())
    out = svc.resolve_capabilities(
        workspace_id="ws-1",
        vertical_norm="education",
        base_domain_id=6,
        capabilities={
            "dimensions": [
                {"column_key": "wt594.calendar_date", "column_name": "calendar_date"},
                {"column_key": "wt594.school_name", "column_name": "school_name"},
            ],
            "time_columns": [],
            "filter_columns": [
                {"column_key": "wt594.is_school_day", "column_name": "is_school_day"},
                {"column_key": "wt594.is_non_instructional_day", "column_name": "is_non_instructional_day"},
            ],
            "domain_metrics": [],
        },
        shortlisted_columns=[],
    )
    assert "CALENDAR_DATE" in out["present"]
    assert "SCHOOL_DAY_FLAG" in out["present"]
    assert "NON_INSTRUCTIONAL_DAY" in out["present"]


def test_capability_service_infers_birth_date_and_age_capabilities() -> None:
    svc = PlannerDomainCapabilityService(sql=_EmptySQL())
    out = svc.resolve_capabilities(
        workspace_id="ws-1",
        vertical_norm="education",
        base_domain_id=21,
        capabilities={
            "dimensions": [
                {"column_key": "wt552.birth_date", "column_name": "birth_date"},
                {"column_key": "wt552.age", "column_name": "age"},
                {"column_key": "wt552.first_name", "column_name": "first_name"},
            ],
            "time_columns": [],
            "filter_columns": [],
            "domain_metrics": [],
        },
        shortlisted_columns=[],
    )
    assert "BIRTH_DATE" in out["present"]
    assert "AGE" in out["present"]


def test_rerank_policy_engine_boosts_supported_domain_and_penalizes_missing_capability() -> None:
    engine = PlannerDomainRerankPolicyEngine(
        capability_service=PlannerDomainCapabilityService(sql=_EmptySQL()),
        policy_service=_FakePolicyService(
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
    strong = engine.evaluate_candidate(
        prompt="Show me all the students enrolled at Barksdale Elementary",
        workspace_id="ws-1",
        vertical_norm="education",
        base_domain_id=9,
        base_score=0.94,
        capabilities={
            "dimensions": [
                {"column_key": "wt552.school_name", "column_name": "school_name", "semantic_type": "attribute.school.name"},
                {"column_key": "wt556.first_name", "column_name": "first_name"},
                {"column_key": "wt570.is_enrolled", "column_name": "is_enrolled"},
            ],
            "time_columns": [],
            "filter_columns": [],
            "domain_metrics": [],
        },
        shortlisted_columns=[],
    )
    weak = engine.evaluate_candidate(
        prompt="Show me all the students enrolled at Barksdale Elementary",
        workspace_id="ws-1",
        vertical_norm="education",
        base_domain_id=15,
        base_score=1.02,
        capabilities={
            "dimensions": [
                {"column_key": "wt590.k_student_xyear", "column_name": "k_student_xyear"},
                {"column_key": "wt590.program_enroll_begin_date", "column_name": "program_enroll_begin_date"},
            ],
            "time_columns": [],
            "filter_columns": [],
            "domain_metrics": [],
        },
        shortlisted_columns=[],
    )

    assert strong["rerank_summary"]["policy_adjustment"] > 0
    assert weak["rerank_summary"]["policy_adjustment"] < 0
    assert strong["final_score"] > weak["final_score"]
    assert "school_literal_present" in strong["prompt_signals"]
    assert any(effect["policy_key"] == "student_listing_enrollment_status" for effect in weak["policy_effects"])


def test_rerank_policy_engine_prefers_birth_date_domain_for_age_extreme_prompt() -> None:
    engine = PlannerDomainRerankPolicyEngine(
        capability_service=PlannerDomainCapabilityService(sql=_EmptySQL()),
        policy_service=_FakePolicyService(
            [
                {
                    "policy_key": "student_age_extreme",
                    "scope_type": "global",
                    "priority": 120,
                    "stop_on_match": 0,
                    "policy_json": {
                        "version": 1,
                        "when_signals_all": ["age_extreme_prompt", "student_listing"],
                        "prefer_capabilities": ["BIRTH_DATE", "AGE", "STUDENT_IDENTITY"],
                        "penalize_missing": ["BIRTH_DATE", "AGE"],
                        "require_for_bonus": ["STUDENT_IDENTITY"],
                        "boost": 0.22,
                        "penalty": 0.28,
                        "max_effect": 0.3,
                    },
                }
            ]
        ),
    )
    strong = engine.evaluate_candidate(
        prompt="Show me the eldest student",
        workspace_id="ws-1",
        vertical_norm="education",
        base_domain_id=21,
        base_score=0.93,
        capabilities={
            "dimensions": [
                {"column_key": "wt552.birth_date", "column_name": "birth_date"},
                {"column_key": "wt552.first_name", "column_name": "first_name"},
            ],
            "time_columns": [],
            "filter_columns": [],
            "domain_metrics": [],
        },
        shortlisted_columns=[],
    )
    weak = engine.evaluate_candidate(
        prompt="Show me the eldest student",
        workspace_id="ws-1",
        vertical_norm="education",
        base_domain_id=15,
        base_score=1.01,
        capabilities={
            "dimensions": [
                {"column_key": "wt590.k_student_xyear", "column_name": "k_student_xyear"},
                {"column_key": "wt590.program_enroll_begin_date", "column_name": "program_enroll_begin_date"},
            ],
            "time_columns": [],
            "filter_columns": [],
            "domain_metrics": [],
        },
        shortlisted_columns=[],
    )

    assert "age_extreme_prompt" in strong["prompt_signals"]
    assert "BIRTH_DATE" in strong["domain_capabilities"]["present"]
    assert strong["rerank_summary"]["policy_adjustment"] > 0
    assert weak["rerank_summary"]["policy_adjustment"] < 0
    assert strong["final_score"] > weak["final_score"]
