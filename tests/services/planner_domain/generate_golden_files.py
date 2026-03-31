"""
Regenerate golden fixture files for planner-domain refactor regression tests.

Run from query-forge-api/:
    python -m tests.services.planner_domain.generate_golden_files

Golden files are saved to tests/services/planner_domain/golden/.
Re-run this script after an explicitly approved behaviour change to update the baselines.
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

# Allow running as __main__ from the query-forge-api/ directory.
_API_ROOT = Path(__file__).parent.parent.parent.parent
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from app.services.planner_domain import service as _svc_module  # noqa: E402
import app.services.planner_domain.pipeline_trace as pipeline_trace_module  # noqa: E402
from app.services.planner_domain.service import PlannerDomainService  # noqa: E402

GOLDEN_DIR = Path(__file__).parent / "golden"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def strip_nondeterministic(debug: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a stable copy of the debug payload suitable for golden-file comparison.

    Volatile fields removed or replaced with sentinels:
    - conversation_id (UUID)
    - technical_details.trace_id / conversation_id (UUIDs)
    - pipeline_trace (contains deeply nested plan objects with uuid filter IDs)
    - pipeline_profile[].ms (wall-clock timing values)
    - unified_llm_trace.llm_prompt_trace.user_prompt (embeds conversation_id for
      follow-up turns when the compact planner includes conversation context)
    """
    out = dict(debug)
    out["conversation_id"] = "<conversation_id>"

    if isinstance(out.get("technical_details"), dict):
        td = dict(out["technical_details"])
        td["trace_id"] = "<trace_id>"
        td["conversation_id"] = "<conversation_id>"
        out["technical_details"] = td

    # pipeline_trace header has trace_id/conversation_id; steps embed full plan
    # objects whose sql_json contains uuid-based filter IDs — strip entirely.
    out.pop("pipeline_trace", None)

    # pipeline_profile: keep step names for structural coverage, drop timing.
    if isinstance(out.get("pipeline_profile"), list):
        out["pipeline_profile"] = [
            {k: v for k, v in step.items() if k != "ms"}
            for step in out["pipeline_profile"]
        ]

    # unified_llm_trace.llm_prompt_trace.user_prompt can embed the prior turn's
    # conversation_id when the compact planner includes conversation context.
    if isinstance(out.get("unified_llm_trace"), dict) and isinstance(
        out["unified_llm_trace"].get("llm_prompt_trace"), dict
    ):
        lpt = {k: v for k, v in out["unified_llm_trace"]["llm_prompt_trace"].items()
               if k != "user_prompt"}
        uit = dict(out["unified_llm_trace"])
        uit["llm_prompt_trace"] = lpt
        out["unified_llm_trace"] = uit

    if isinstance(out.get("shared_pipeline"), dict):
        out["shared_pipeline"] = _normalize_nested_pipeline_debug(out["shared_pipeline"])

    return out


def _normalize_nested_pipeline_debug(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if key == "ms":
                continue
            if key == "timings_ms" and isinstance(item, dict):
                normalized[key] = {str(name): 0 for name in item}
                continue
            normalized[str(key)] = _normalize_nested_pipeline_debug(item)
        return normalized
    if isinstance(value, list):
        return [_normalize_nested_pipeline_debug(item) for item in value]
    return value


def _reset_loggers(tmp_dir: str) -> None:
    """Isolate pipeline loggers so they do not write to production log files."""
    m = pipeline_trace_module
    m.QF_PLAN_DOMAIN_TIMING_PROFILE_LOG_FILE = str(Path(tmp_dir) / "profile.log")
    m.QF_PLAN_DOMAIN_PIPELINE_TRACE_LOG_FILE = str(Path(tmp_dir) / "trace.jsonl")

    for name in (m._PROFILE_LOGGER_NAME, m._TRACE_LOGGER_NAME):
        lg = logging.getLogger(name)
        for h in list(lg.handlers):
            lg.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
    m._PROFILE_LOGGER_INITIALIZED = False
    m._TRACE_LOGGER_INITIALIZED = False


def _save(name: str, response: Dict[str, Any]) -> None:
    """Save the stripped debug payload (response['debug']) to a golden file."""
    debug = response.get("debug") or {}
    path = GOLDEN_DIR / f"{name}.json"
    path.write_text(json.dumps(strip_nondeterministic(debug), indent=2, default=str))
    print(f"  saved {path.name}")


# ---------------------------------------------------------------------------
# Shared fake service building blocks
# ---------------------------------------------------------------------------

class _MemoryConversationStore:
    def __init__(self) -> None:
        self._rows: dict = {}

    def get_state(self, *, workspace_id, user_id, conversation_id):
        return self._rows.get((workspace_id, user_id, conversation_id))

    def save_state(self, *, workspace_id, user_id, conversation_id, state, qf_ttl_seconds):
        self._rows[(workspace_id, user_id, conversation_id)] = dict(state)


def _make_caps(domain_id: int, dimensions: list, metrics: list | None = None,
               overlay_metrics: list | None = None, time_columns: list | None = None):
    """Return a capabilities-service stub for a fixed domain."""
    caps = {
        "domain_id": domain_id,
        "domain_version": 1,
        "dimensions": dimensions,
        "domain_metrics": metrics or [],
        "user_metrics": [],
        "overlay_metrics": overlay_metrics or [],
        "time_columns": time_columns or [],
    }

    class _Svc:
        def get_domain_capabilities(self, *, workspace_id, user_id, domain_id, vertical_norm):
            return caps

    return _Svc()


def _make_vector(domain_id: int, name: str):
    class _Svc:
        def search_domains(self, **kwargs):
            return {"results": [{"domain_id": domain_id, "name": name, "score": 0.9}]}
    return _Svc()


# ---------------------------------------------------------------------------
# Scenario 1: Enrolled students at a specific school
# ---------------------------------------------------------------------------

def _capture_enrolled_students(tmp_dir: str) -> None:
    class _LLM:
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

    _reset_loggers(tmp_dir)
    svc = PlannerDomainService(
        capabilities_service=_make_caps(
            domain_id=6,
            dimensions=[
                {"column_key": "wt24.student_unique_id", "label": "Student ID",
                 "data_type": "string", "filterable": False,
                 "workspace_table_id": 24, "model_column_id": 1001, "column_name": "student_unique_id",
                 "semantic_concept_key": "STUDENT_ID"},
                {"column_key": "wt20.school_name", "label": "School Name",
                 "data_type": "string", "filterable": True,
                 "workspace_table_id": 20, "model_column_id": 201, "column_name": "school_name",
                 "semantic_concept_key": "SCHOOL_NAME"},
                {"column_key": "wt24.is_enrolled", "label": "Is Enrolled",
                 "data_type": "int", "filterable": True,
                 "workspace_table_id": 24, "model_column_id": 1002, "column_name": "is_enrolled",
                 "semantic_concept_key": "ENROLLMENT_STATUS"},
            ],
        ),
        domain_vector_service=_make_vector(6, "Student Enrollment"),
        llm_client=_LLM(),
    )
    out = svc.plan(
        {"workspace_id": "ws-1", "vertical_norm": "education",
         "base_domain_id": 6, "prompt": "show me students enrolled at Barksdale Elementary",
         "debug": True},
        user_id="user-1",
    )
    _save("enrolled_students", out)


# ---------------------------------------------------------------------------
# Scenario 2: Calendar days off
# ---------------------------------------------------------------------------

def _capture_calendar_days_off(tmp_dir: str) -> None:
    class _LLM:
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

    _reset_loggers(tmp_dir)
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
                 "workspace_table_id": 20, "model_column_id": 201, "column_name": "school_name",
                 "semantic_concept_key": "SCHOOL_NAME"},
            ],
        ),
        domain_vector_service=_make_vector(7, "School Calendar"),
        llm_client=_LLM(),
    )
    out = svc.plan(
        {"workspace_id": "ws-1", "vertical_norm": "education",
         "base_domain_id": 7,
         "prompt": "show me the days off at Barksdale Elementary in December",
         "debug": True},
        user_id="user-1",
    )
    _save("calendar_days_off", out)


# ---------------------------------------------------------------------------
# Scenario 3: Subgroup / race alias normalization
# ---------------------------------------------------------------------------

def _capture_race_alias_normalization(tmp_dir: str) -> None:
    class _LLM:
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
                        {"column_key": "wt24.race_ethnicity", "op": "=",
                         "value": "African American"},
                    ],
                    "time": {},
                    "grouping": {
                        "group_by": ["wt24.student_unique_id"],
                        "order_by": [],
                        "limit": 200,
                    },
                },
                "content": "{}", "raw_text": "{}",
            }

    class _AliasResolver:
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

    _reset_loggers(tmp_dir)
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
        llm_client=_LLM(),
        value_alias_resolver=_AliasResolver(),
    )
    out = svc.plan(
        {"workspace_id": "ws-1", "vertical_norm": "education",
         "base_domain_id": 6,
         "prompt": "show me all the african american students currently enrolled",
         "debug": True},
        user_id="user-1",
    )
    _save("race_alias_normalization", out)


# ---------------------------------------------------------------------------
# Scenario 4: Age-extreme prompt
# ---------------------------------------------------------------------------

def _capture_age_extreme(tmp_dir: str) -> None:
    class _LLM:
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

    _reset_loggers(tmp_dir)
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
        llm_client=_LLM(),
    )
    out = svc.plan(
        {"workspace_id": "ws-1", "vertical_norm": "education",
         "base_domain_id": 8,
         "prompt": "show me the oldest student",
         "debug": True},
        user_id="user-1",
    )
    _save("age_extreme", out)


# ---------------------------------------------------------------------------
# Scenario 5: Birth-month prompt
# ---------------------------------------------------------------------------

def _capture_birth_month(tmp_dir: str) -> None:
    class _LLM:
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
                    "filters": [
                        {"column_key": "wt24.birth_date", "op": "month", "value": 1},
                    ],
                    "time": {},
                    "grouping": {
                        "group_by": ["wt24.student_unique_id"],
                        "order_by": [],
                        "limit": 200,
                    },
                },
                "content": "{}", "raw_text": "{}",
            }

    _reset_loggers(tmp_dir)
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
        llm_client=_LLM(),
    )
    out = svc.plan(
        {"workspace_id": "ws-1", "vertical_norm": "education",
         "base_domain_id": 8,
         "prompt": "show me students born in January",
         "debug": True},
        user_id="user-1",
    )
    _save("birth_month", out)


# ---------------------------------------------------------------------------
# Scenario 6: School year / semester prompt
# ---------------------------------------------------------------------------

def _capture_school_year_semester(tmp_dir: str) -> None:
    class _LLM:
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

    _reset_loggers(tmp_dir)
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
        llm_client=_LLM(),
    )
    out = svc.plan(
        {"workspace_id": "ws-1", "vertical_norm": "education",
         "base_domain_id": 6,
         "prompt": "show me enrollment data by semester for school year 2025",
         "debug": True},
        user_id="user-1",
    )
    _save("school_year_semester", out)


# ---------------------------------------------------------------------------
# Scenario 7: Top/bottom metric prompt
# ---------------------------------------------------------------------------

def _capture_top_bottom_ranking(tmp_dir: str) -> None:
    class _LLM:
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

    _reset_loggers(tmp_dir)
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
        llm_client=_LLM(),
    )
    out = svc.plan(
        {"workspace_id": "ws-1", "vertical_norm": "education",
         "base_domain_id": 6,
         "prompt": "show me the top 10 schools by enrollment",
         "debug": True},
        user_id="user-1",
    )
    _save("top_bottom_ranking", out)


# ---------------------------------------------------------------------------
# Scenario 8: Follow-up sort/edit prompt
# ---------------------------------------------------------------------------

def _capture_followup_sort(tmp_dir: str) -> None:
    class _LLM:
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

    store = _MemoryConversationStore()
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

    _reset_loggers(tmp_dir)
    llm = _LLM()
    svc = PlannerDomainService(
        capabilities_service=caps,
        domain_vector_service=_make_vector(5, "Staff & Assignments"),
        llm_client=llm,
        conversation_store=store,
    )

    # Turn 1: base query
    first = svc.plan(
        {"workspace_id": "ws-1", "vertical_norm": "education",
         "base_domain_id": 5,
         "prompt": "show me the staff at barksdale elementary",
         "debug": True},
        user_id="user-1",
    )
    _save("followup_sort_turn1", first)

    # Turn 2: follow-up sort
    _reset_loggers(tmp_dir)
    second = svc.plan(
        {"workspace_id": "ws-1",
         "prompt": "sort by position",
         "conversation_id": first["conversation_id"],
         "debug": True},
        user_id="user-1",
    )
    _save("followup_sort_turn2", second)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

SCENARIOS = [
    ("enrolled students", _capture_enrolled_students),
    ("calendar days off", _capture_calendar_days_off),
    ("race alias normalization", _capture_race_alias_normalization),
    ("age extreme", _capture_age_extreme),
    ("birth month", _capture_birth_month),
    ("school year / semester", _capture_school_year_semester),
    ("top/bottom ranking", _capture_top_bottom_ranking),
    ("follow-up sort (2 turns)", _capture_followup_sort),
]


def generate_all() -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch.object(_svc_module, "PLANNER_UNIFIED_LLM", False):
            for label, fn in SCENARIOS:
                print(f"Capturing: {label}")
                fn(tmp_dir)
    print(f"\nDone. {len(SCENARIOS) + 1} golden files written to {GOLDEN_DIR}/")


if __name__ == "__main__":
    generate_all()
