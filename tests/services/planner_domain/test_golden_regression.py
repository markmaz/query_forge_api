"""
Golden-file regression tests for PlannerDomainService.

After each refactoring phase, these tests compare the full plan() response
(with debug=True) against the baseline JSON fixtures in golden/.

Any key addition, removal, or value change causes a failure — signalling an
unintended behaviour change that must be investigated before the phase is
committed.

To regenerate baselines after an approved behaviour change, run:
    python3 -m tests.services.planner_domain.generate_golden_files
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from app.services.planner_domain import service as planner_domain_service_module
import app.services.planner_domain.pipeline_trace as pipeline_trace_module
from tests.services.planner_domain.generate_golden_files import (
    _MemoryConversationStore,
    _capture_enrolled_students,
    _capture_calendar_days_off,
    _capture_race_alias_normalization,
    _capture_age_extreme,
    _capture_birth_month,
    _capture_school_year_semester,
    _capture_top_bottom_ranking,
    _capture_followup_sort,
    _make_caps,
    _make_vector,
    strip_nondeterministic,
)
from app.services.planner_domain.service import PlannerDomainService

GOLDEN_DIR = Path(__file__).parent / "golden"


# ---------------------------------------------------------------------------
# Autouse fixtures – mirror the ones in test_service.py
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_golden(name: str) -> dict:
    path = GOLDEN_DIR / f"{name}.json"
    return json.loads(path.read_text())


def _assert_matches_golden(response: dict, golden_name: str) -> None:
    """
    Compare the stripped debug payload against the golden file.
    Fails on any key addition, removal, or value change.
    """
    debug = response.get("debug") or {}
    actual = strip_nondeterministic(debug)
    expected = _load_golden(golden_name)
    assert actual == expected, (
        f"Golden file mismatch for '{golden_name}'.\n"
        "If this change is intentional, re-run generate_golden_files.py to update baselines."
    )


# ---------------------------------------------------------------------------
# Scenario fake services (inline — mirrors generate_golden_files.py exactly)
# ---------------------------------------------------------------------------

class _EnrolledStudentsLLM:
    def chat_json_with_trace(self, **kwargs):
        user_prompt = str(kwargs.get("user_prompt") or "")
        if "Task: Extract lightweight planning slots" in user_prompt:
            return {"parsed": {"intent": "list", "entity": "students",
                               "constraints": [], "time_phrases": []},
                    "content": "{}", "raw_text": "{}"}
        return {
            "parsed": {
                "intent": "list",
                "selects": {
                    "dimensions": [
                        {"column_key": "wt24.student_unique_id", "label": "Student ID"},
                        {"column_key": "wt20.school_name", "label": "School Name"},
                    ],
                    "metrics": [],
                },
                "filters": [
                    {"column_key": "wt20.school_name", "op": "=", "value": "Barksdale Elementary"},
                    {"column_key": "wt24.is_enrolled", "op": "=", "value": 1},
                ],
                "time": {},
                "grouping": {
                    "group_by": ["wt24.student_unique_id", "wt20.school_name"],
                    "order_by": [],
                    "limit": 200,
                },
            },
            "content": "{}", "raw_text": "{}",
        }


class _CalendarDaysOffLLM:
    def chat_json_with_trace(self, **kwargs):
        user_prompt = str(kwargs.get("user_prompt") or "")
        if "Task: Extract lightweight planning slots" in user_prompt:
            return {"parsed": {"intent": "list", "entity": "calendar",
                               "constraints": [], "time_phrases": ["december"]},
                    "content": "{}", "raw_text": "{}"}
        return {
            "parsed": {
                "intent": "list",
                "selects": {
                    "dimensions": [
                        {"column_key": "wt30.day_date", "label": "Day Date"},
                        {"column_key": "wt30.event_type", "label": "Event Type"},
                    ],
                    "metrics": [],
                },
                "filters": [
                    {"column_key": "wt30.event_type", "op": "=", "value": "Non-school day"},
                ],
                "time": {"start": "2025-12-01", "end": "2025-12-31"},
                "grouping": {"group_by": ["wt30.day_date", "wt30.event_type"],
                             "order_by": [{"by": "wt30.day_date", "dir": "asc"}],
                             "limit": None},
            },
            "content": "{}", "raw_text": "{}",
        }


class _RaceAliasLLM:
    def chat_json_with_trace(self, **kwargs):
        user_prompt = str(kwargs.get("user_prompt") or "")
        if "Task: Extract lightweight planning slots" in user_prompt:
            return {"parsed": {"intent": "list", "entity": "students",
                               "constraints": [{"kind": "unknown", "text": "african american",
                                                "op": "eq", "value_hint": "African American",
                                                "notes": None}],
                               "time_phrases": []},
                    "content": "{}", "raw_text": "{}"}
        return {
            "parsed": {
                "intent": "list",
                "selects": {
                    "dimensions": [
                        {"column_key": "wt24.student_unique_id", "label": "Student ID"},
                        {"column_key": "wt24.race_ethnicity", "label": "Race/Ethnicity"},
                    ],
                    "metrics": [],
                },
                "filters": [
                    {"column_key": "wt24.race_ethnicity", "op": "=", "value": "African American"},
                ],
                "time": {},
                "grouping": {"group_by": ["wt24.student_unique_id"], "order_by": [], "limit": 200},
            },
            "content": "{}", "raw_text": "{}",
        }


class _RaceAliasResolver:
    def resolve(self, *, prompt: str, vertical_norm: str):
        return [
            {
                "column_key": "wt24.race_ethnicity",
                "column_name": "race_ethnicity",
                "kind": "semantic_value_alias",
                "text": "african american",
                "op": "eq",
                "value_hint": "African American",
                "canonical_value": "Black or African American",
                "notes": "semantic_alias:RACE_ETHNICITY",
            }
        ]


class _AgeExtremeLLM:
    def chat_json_with_trace(self, **kwargs):
        user_prompt = str(kwargs.get("user_prompt") or "")
        if "Task: Extract lightweight planning slots" in user_prompt:
            return {"parsed": {"intent": "list", "entity": "students",
                               "constraints": [], "time_phrases": []},
                    "content": "{}", "raw_text": "{}"}
        return {
            "parsed": {
                "intent": "list",
                "selects": {
                    "dimensions": [
                        {"column_key": "wt24.student_unique_id", "label": "Student ID"},
                        {"column_key": "wt24.birth_date", "label": "Birth Date"},
                    ],
                    "metrics": [],
                },
                "filters": [],
                "time": {},
                "grouping": {
                    "group_by": ["wt24.student_unique_id", "wt24.birth_date"],
                    "order_by": [{"by": "wt24.birth_date", "dir": "asc"}],
                    "limit": 1,
                },
            },
            "content": "{}", "raw_text": "{}",
        }


class _BirthMonthLLM:
    def chat_json_with_trace(self, **kwargs):
        user_prompt = str(kwargs.get("user_prompt") or "")
        if "Task: Extract lightweight planning slots" in user_prompt:
            return {"parsed": {"intent": "list", "entity": "students",
                               "constraints": [], "time_phrases": ["born in january"]},
                    "content": "{}", "raw_text": "{}"}
        return {
            "parsed": {
                "intent": "list",
                "selects": {
                    "dimensions": [
                        {"column_key": "wt24.student_unique_id", "label": "Student ID"},
                        {"column_key": "wt24.birth_date", "label": "Birth Date"},
                    ],
                    "metrics": [],
                },
                "filters": [{"column_key": "wt24.birth_date", "op": "month", "value": 1}],
                "time": {},
                "grouping": {
                    "group_by": ["wt24.student_unique_id"],
                    "order_by": [],
                    "limit": 200,
                },
            },
            "content": "{}", "raw_text": "{}",
        }


class _SchoolYearSemesterLLM:
    def chat_json_with_trace(self, **kwargs):
        user_prompt = str(kwargs.get("user_prompt") or "")
        if "Task: Extract lightweight planning slots" in user_prompt:
            return {"parsed": {"intent": "aggregate", "entity": "enrollment",
                               "constraints": [], "time_phrases": ["school year 2025"]},
                    "content": "{}", "raw_text": "{}"}
        return {
            "parsed": {
                "intent": "aggregate",
                "selects": {
                    "dimensions": [
                        {"column_key": "wt24.school_year", "label": "School Year"},
                        {"column_key": "wt24.semester", "label": "Semester"},
                    ],
                    "metrics": [
                        {"metric_ref": "domain_metric:enrollment_count",
                         "label": "Enrollment Count"},
                    ],
                },
                "filters": [
                    {"column_key": "wt24.school_year", "op": "=", "value": 2025},
                ],
                "time": {},
                "grouping": {
                    "group_by": ["wt24.school_year", "wt24.semester"],
                    "order_by": [],
                    "limit": 200,
                },
            },
            "content": "{}", "raw_text": "{}",
        }


class _TopBottomLLM:
    def chat_json_with_trace(self, **kwargs):
        user_prompt = str(kwargs.get("user_prompt") or "")
        if "Task: Extract lightweight planning slots" in user_prompt:
            return {"parsed": {"intent": "aggregate", "entity": "schools",
                               "constraints": [], "time_phrases": []},
                    "content": "{}", "raw_text": "{}"}
        return {
            "parsed": {
                "intent": "aggregate",
                "selects": {
                    "dimensions": [
                        {"column_key": "wt20.school_name", "label": "School Name"},
                    ],
                    "metrics": [
                        {"metric_ref": "domain_metric:enrollment_count",
                         "label": "Enrollment Count"},
                    ],
                },
                "filters": [],
                "time": {},
                "grouping": {
                    "group_by": ["wt20.school_name"],
                    "order_by": [{"by": "metric:domain_metric:enrollment_count", "dir": "desc"}],
                    "limit": 10,
                },
            },
            "content": "{}", "raw_text": "{}",
        }


class _FollowupLLM:
    def chat_json_with_trace(self, **kwargs):
        user_prompt = str(kwargs.get("user_prompt") or "")
        prompt_l = user_prompt.lower()
        if "task: extract lightweight planning slots" in prompt_l:
            return {"parsed": {"intent": "list", "entity": "staff",
                               "constraints": [], "time_phrases": []},
                    "content": "{}", "raw_text": "{}"}
        if "sort by position" in prompt_l:
            return {
                "parsed": {
                    "intent": "list",
                    "selects": {
                        "dimensions": [
                            {"column_key": "wt30.position_title", "label": "Position Title"},
                        ],
                        "metrics": [],
                    },
                    "filters": [],
                    "time": {},
                    "grouping": {
                        "group_by": ["wt30.position_title"],
                        "order_by": [{"by": "wt30.position_title", "dir": "asc"}],
                        "limit": None,
                    },
                },
                "content": "{}", "raw_text": "{}",
            }
        return {
            "parsed": {
                "intent": "list",
                "selects": {
                    "dimensions": [
                        {"column_key": "wt20.school_name", "label": "School Name"},
                        {"column_key": "wt23.first_name", "label": "First Name"},
                        {"column_key": "wt23.last_name", "label": "Last Name"},
                        {"column_key": "wt30.position_title", "label": "Position Title"},
                    ],
                    "metrics": [],
                },
                "filters": [
                    {"column_key": "wt20.school_name", "op": "=",
                     "value": "Barksdale Elementary"},
                ],
                "time": {},
                "grouping": {
                    "group_by": ["wt20.school_name", "wt23.first_name",
                                 "wt23.last_name", "wt30.position_title"],
                    "order_by": [],
                    "limit": None,
                },
            },
            "content": "{}", "raw_text": "{}",
        }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_golden_enrolled_students() -> None:
    svc = PlannerDomainService(
        capabilities_service=_make_caps(
            domain_id=6,
            dimensions=[
                {"column_key": "wt24.student_unique_id", "label": "Student ID",
                 "data_type": "string", "filterable": False,
                 "workspace_table_id": 24, "model_column_id": 1001, "column_name": "student_unique_id"},
                {"column_key": "wt20.school_name", "label": "School Name",
                 "data_type": "string", "filterable": True,
                 "workspace_table_id": 20, "model_column_id": 201, "column_name": "school_name"},
                {"column_key": "wt24.is_enrolled", "label": "Is Enrolled",
                 "data_type": "int", "filterable": True,
                 "workspace_table_id": 24, "model_column_id": 1002, "column_name": "is_enrolled"},
            ],
        ),
        domain_vector_service=_make_vector(6, "Student Enrollment"),
        llm_client=_EnrolledStudentsLLM(),
    )
    out = svc.plan(
        {"workspace_id": "ws-1", "vertical_norm": "education",
         "base_domain_id": 6, "prompt": "show me students enrolled at Barksdale Elementary",
         "debug": True},
        user_id="user-1",
    )
    _assert_matches_golden(out, "enrolled_students")


def test_golden_calendar_days_off() -> None:
    svc = PlannerDomainService(
        capabilities_service=_make_caps(
            domain_id=7,
            dimensions=[
                {"column_key": "wt30.day_date", "label": "Day Date",
                 "data_type": "date", "filterable": True,
                 "workspace_table_id": 30, "model_column_id": 301, "column_name": "day_date"},
                {"column_key": "wt30.event_type", "label": "Event Type",
                 "data_type": "string", "filterable": True,
                 "workspace_table_id": 30, "model_column_id": 302, "column_name": "event_type"},
                {"column_key": "wt20.school_name", "label": "School Name",
                 "data_type": "string", "filterable": True,
                 "workspace_table_id": 20, "model_column_id": 201, "column_name": "school_name"},
            ],
        ),
        domain_vector_service=_make_vector(7, "School Calendar"),
        llm_client=_CalendarDaysOffLLM(),
    )
    out = svc.plan(
        {"workspace_id": "ws-1", "vertical_norm": "education",
         "base_domain_id": 7,
         "prompt": "show me the days off at Barksdale Elementary in December",
         "debug": True},
        user_id="user-1",
    )
    _assert_matches_golden(out, "calendar_days_off")


def test_golden_race_alias_normalization() -> None:
    svc = PlannerDomainService(
        capabilities_service=_make_caps(
            domain_id=6,
            dimensions=[
                {"column_key": "wt24.student_unique_id", "label": "Student ID",
                 "data_type": "string", "filterable": False,
                 "workspace_table_id": 24, "model_column_id": 1001, "column_name": "student_unique_id"},
                {"column_key": "wt24.race_ethnicity", "label": "Race/Ethnicity",
                 "data_type": "string", "filterable": True,
                 "workspace_table_id": 24, "model_column_id": 1004, "column_name": "race_ethnicity"},
            ],
        ),
        domain_vector_service=_make_vector(6, "Student Demographics"),
        llm_client=_RaceAliasLLM(),
        value_alias_resolver=_RaceAliasResolver(),
    )
    out = svc.plan(
        {"workspace_id": "ws-1", "vertical_norm": "education",
         "base_domain_id": 6,
         "prompt": "show me all the african american students currently enrolled",
         "debug": True},
        user_id="user-1",
    )
    _assert_matches_golden(out, "race_alias_normalization")


def test_golden_age_extreme() -> None:
    svc = PlannerDomainService(
        capabilities_service=_make_caps(
            domain_id=8,
            dimensions=[
                {"column_key": "wt24.student_unique_id", "label": "Student ID",
                 "data_type": "string", "filterable": False,
                 "workspace_table_id": 24, "model_column_id": 1001, "column_name": "student_unique_id"},
                {"column_key": "wt24.birth_date", "label": "Birth Date",
                 "data_type": "date", "filterable": True,
                 "workspace_table_id": 24, "model_column_id": 1010, "column_name": "birth_date"},
            ],
        ),
        domain_vector_service=_make_vector(8, "Student Demographics"),
        llm_client=_AgeExtremeLLM(),
    )
    out = svc.plan(
        {"workspace_id": "ws-1", "vertical_norm": "education",
         "base_domain_id": 8,
         "prompt": "show me the oldest student",
         "debug": True},
        user_id="user-1",
    )
    _assert_matches_golden(out, "age_extreme")


def test_golden_birth_month() -> None:
    svc = PlannerDomainService(
        capabilities_service=_make_caps(
            domain_id=8,
            dimensions=[
                {"column_key": "wt24.student_unique_id", "label": "Student ID",
                 "data_type": "string", "filterable": False,
                 "workspace_table_id": 24, "model_column_id": 1001, "column_name": "student_unique_id"},
                {"column_key": "wt24.birth_date", "label": "Birth Date",
                 "data_type": "date", "filterable": True,
                 "workspace_table_id": 24, "model_column_id": 1010, "column_name": "birth_date"},
            ],
        ),
        domain_vector_service=_make_vector(8, "Student Demographics"),
        llm_client=_BirthMonthLLM(),
    )
    out = svc.plan(
        {"workspace_id": "ws-1", "vertical_norm": "education",
         "base_domain_id": 8,
         "prompt": "show me students born in January",
         "debug": True},
        user_id="user-1",
    )
    _assert_matches_golden(out, "birth_month")


def test_golden_school_year_semester() -> None:
    svc = PlannerDomainService(
        capabilities_service=_make_caps(
            domain_id=6,
            dimensions=[
                {"column_key": "wt24.school_year", "label": "School Year",
                 "data_type": "int", "filterable": True,
                 "workspace_table_id": 24, "model_column_id": 1020, "column_name": "school_year"},
                {"column_key": "wt24.semester", "label": "Semester",
                 "data_type": "string", "filterable": True,
                 "workspace_table_id": 24, "model_column_id": 1021, "column_name": "semester"},
            ],
            metrics=[
                {"metric_key": "enrollment_count", "label": "Enrollment Count",
                 "kind": "count", "agg": "count"},
            ],
        ),
        domain_vector_service=_make_vector(6, "Student Enrollment"),
        llm_client=_SchoolYearSemesterLLM(),
    )
    out = svc.plan(
        {"workspace_id": "ws-1", "vertical_norm": "education",
         "base_domain_id": 6,
         "prompt": "show me enrollment data by semester for school year 2025",
         "debug": True},
        user_id="user-1",
    )
    _assert_matches_golden(out, "school_year_semester")


def test_golden_top_bottom_ranking() -> None:
    svc = PlannerDomainService(
        capabilities_service=_make_caps(
            domain_id=6,
            dimensions=[
                {"column_key": "wt20.school_name", "label": "School Name",
                 "data_type": "string", "filterable": True,
                 "workspace_table_id": 20, "model_column_id": 201, "column_name": "school_name"},
            ],
            metrics=[
                {"metric_key": "enrollment_count", "label": "Enrollment Count",
                 "kind": "count", "agg": "count"},
            ],
        ),
        domain_vector_service=_make_vector(6, "Student Enrollment"),
        llm_client=_TopBottomLLM(),
    )
    out = svc.plan(
        {"workspace_id": "ws-1", "vertical_norm": "education",
         "base_domain_id": 6,
         "prompt": "show me the top 10 schools by enrollment",
         "debug": True},
        user_id="user-1",
    )
    _assert_matches_golden(out, "top_bottom_ranking")


def test_golden_followup_sort_turn1() -> None:
    store = _MemoryConversationStore()
    llm = _FollowupLLM()
    caps = _make_caps(
        domain_id=5,
        dimensions=[
            {"column_key": "wt20.school_name", "label": "School Name",
             "data_type": "string", "filterable": True,
             "workspace_table_id": 20, "model_column_id": 201, "column_name": "school_name"},
            {"column_key": "wt23.first_name", "label": "First Name",
             "data_type": "string", "filterable": True,
             "workspace_table_id": 23, "model_column_id": 315, "column_name": "first_name"},
            {"column_key": "wt23.last_name", "label": "Last Name",
             "data_type": "string", "filterable": True,
             "workspace_table_id": 23, "model_column_id": 316, "column_name": "last_name"},
            {"column_key": "wt30.position_title", "label": "Position Title",
             "data_type": "string", "filterable": True,
             "workspace_table_id": 30, "model_column_id": 602, "column_name": "position_title"},
        ],
    )
    svc = PlannerDomainService(
        capabilities_service=caps,
        domain_vector_service=_make_vector(5, "Staff & Assignments"),
        llm_client=llm,
        conversation_store=store,
    )
    first = svc.plan(
        {"workspace_id": "ws-1", "vertical_norm": "education",
         "base_domain_id": 5,
         "prompt": "show me the staff at barksdale elementary",
         "debug": True},
        user_id="user-1",
    )
    _assert_matches_golden(first, "followup_sort_turn1")


def test_golden_followup_sort_turn2() -> None:
    store = _MemoryConversationStore()
    llm = _FollowupLLM()
    caps = _make_caps(
        domain_id=5,
        dimensions=[
            {"column_key": "wt20.school_name", "label": "School Name",
             "data_type": "string", "filterable": True,
             "workspace_table_id": 20, "model_column_id": 201, "column_name": "school_name"},
            {"column_key": "wt23.first_name", "label": "First Name",
             "data_type": "string", "filterable": True,
             "workspace_table_id": 23, "model_column_id": 315, "column_name": "first_name"},
            {"column_key": "wt23.last_name", "label": "Last Name",
             "data_type": "string", "filterable": True,
             "workspace_table_id": 23, "model_column_id": 316, "column_name": "last_name"},
            {"column_key": "wt30.position_title", "label": "Position Title",
             "data_type": "string", "filterable": True,
             "workspace_table_id": 30, "model_column_id": 602, "column_name": "position_title"},
        ],
    )
    svc = PlannerDomainService(
        capabilities_service=caps,
        domain_vector_service=_make_vector(5, "Staff & Assignments"),
        llm_client=llm,
        conversation_store=store,
    )
    # Turn 1: establish conversation state
    first = svc.plan(
        {"workspace_id": "ws-1", "vertical_norm": "education",
         "base_domain_id": 5,
         "prompt": "show me the staff at barksdale elementary"},
        user_id="user-1",
    )
    # Turn 2: follow-up sort
    second = svc.plan(
        {"workspace_id": "ws-1",
         "prompt": "sort by position",
         "conversation_id": first["conversation_id"],
         "debug": True},
        user_id="user-1",
    )
    _assert_matches_golden(second, "followup_sort_turn2")
