from __future__ import annotations

from app.services.planner_domain import service as planner_domain_service_module
from app.services.planner_domain.service import (
    PlannerDomainService,
    _district_county_retry_hint,
)


class _FakeCapabilitiesService:
    def get_domain_capabilities(self, *, workspace_id, user_id, domain_id, vertical_norm):
        del workspace_id, user_id, vertical_norm
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

    def resolve(self, *, prompt: str, vertical_norm: str):
        del prompt, vertical_norm
        if self.should_raise:
            raise RuntimeError("boom")
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
    assert out["plan_json_v2"]["selects"]["metrics"][0]["metric_ref"] == "overlay:students_per_teacher"
    assert out["plan_json_v2"]["selects"]["dimensions"][0]["column_key"] == "wt20.county_fips_code"
    assert "explanation" in out
    assert out["explanation"]["domain"]["selected_domain_id"] == 6
    assert out["explanation"]["metrics"][0]["metric_ref"] == "overlay:students_per_teacher"
    assert "I used the" in out["explanation"]["summary"]
    assert out["explanation"]["domain"]["reason"]
    sql_metrics = ((out["sql_json"].get("aggs") or {}).get("metrics") or [])
    assert sql_metrics
    assert sql_metrics[0]["fn"] == "overlay_metric"
    assert sql_metrics[0]["overlay_key"] == "students_per_teacher"


def test_explanation_summary_can_be_polished_by_llm(monkeypatch) -> None:
    class _StaffCapsService:
        def get_domain_capabilities(self, *, workspace_id, user_id, domain_id, vertical_norm):
            del workspace_id, user_id, vertical_norm
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
    svc = PlannerDomainService(
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
                "column_key": "wt24.last_name",
                "column_name": "last_name",
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

    compact = svc._compact_capabilities_for_llm(  # noqa: SLF001
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
        prompt="Show students not born in the US",
    )

    first_three = [row["column_key"] for row in compact["dimensions"][:3]]
    assert first_three == ["wt24.student_unique_id", "wt24.first_name", "wt24.last_name"]


def test_compact_capabilities_prepends_student_identity_from_slot_hints() -> None:
    svc = PlannerDomainService(
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
                "column_key": "wt24.last_name",
                "column_name": "last_name",
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

    compact = svc._compact_capabilities_for_llm(  # noqa: SLF001
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
        prompt="students not born in the US",
        slot_hints={"intent": "list", "entity": "students"},
    )

    first_three = [row["column_key"] for row in compact["dimensions"][:3]]
    assert first_three == ["wt24.student_unique_id", "wt24.first_name", "wt24.last_name"]


def test_compact_capabilities_includes_nativity_filter_columns() -> None:
    svc = PlannerDomainService(
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

    compact = svc._compact_capabilities_for_llm(  # noqa: SLF001
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
        prompt="list all the students not born in the us",
    )

    dim_keys = {row["column_key"] for row in compact["dimensions"]}
    filter_keys = {row["column_key"] for row in compact["filter_columns"]}
    assert "wt24.birth_country" not in dim_keys
    assert "wt24.birth_country" in filter_keys


def test_compact_capabilities_prepends_school_listing_identity_columns() -> None:
    svc = PlannerDomainService(
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

    compact = svc._compact_capabilities_for_llm(  # noqa: SLF001
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
        prompt="Show me all the schools in Clarksville, TN",
    )

    first_three = [row["column_key"] for row in compact["dimensions"][:3]]
    assert first_three == ["wt20.school_name", "wt20.lea_name", "wt20.school_number"]


def test_compact_capabilities_city_state_prefers_state_code_over_state_school_code() -> None:
    svc = PlannerDomainService(
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

    compact = svc._compact_capabilities_for_llm(  # noqa: SLF001
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
    svc = PlannerDomainService(
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
                "filterable": True,
                "workspace_table_id": 30,
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
        ],
        "time_columns": [],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
    }
    shortlisted = [{"column_key": "wt30.k_school", "column_name": "k_school", "workspace_table_id": 30}]

    compact = svc._compact_capabilities_for_llm(  # noqa: SLF001
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
        prompt="Show me all the staff for Rossview Elementary",
    )

    filter_keys = [row["column_key"] for row in compact["filter_columns"]]
    assert "wt20.school_name" in filter_keys
    assert "wt30.k_school" not in filter_keys


def test_compact_capabilities_principal_school_name_filter_avoids_k_school() -> None:
    svc = PlannerDomainService(
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
                "filterable": True,
                "workspace_table_id": 30,
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
    shortlisted = [{"column_key": "wt30.k_school", "column_name": "k_school", "workspace_table_id": 30}]

    compact = svc._compact_capabilities_for_llm(  # noqa: SLF001
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
        prompt="Show me the principal for Barksdale Elementary",
    )

    filter_keys = [row["column_key"] for row in compact["filter_columns"]]
    assert "wt20.school_name" in filter_keys
    assert "wt30.k_school" not in filter_keys


def test_compact_capabilities_staff_role_filter_prefers_position_title_over_classification() -> None:
    svc = PlannerDomainService(
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
                "filterable": True,
                "workspace_table_id": 30,
            },
            {
                "column_key": "wt30.position_title",
                "column_name": "position_title",
                "filterable": True,
                "workspace_table_id": 30,
            },
            {
                "column_key": "wt31.classroom_position",
                "column_name": "classroom_position",
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

    compact = svc._compact_capabilities_for_llm(  # noqa: SLF001
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
        prompt="Who is the principal at Rossview Elementary",
    )

    filter_keys = [row["column_key"] for row in compact["filter_columns"]]
    assert "wt30.position_title" in filter_keys
    assert "wt30.staff_classification" not in filter_keys


def test_compact_capabilities_person_lookup_prefers_canonical_name_columns_over_preferred() -> None:
    svc = PlannerDomainService(
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

    compact = svc._compact_capabilities_for_llm(  # noqa: SLF001
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
    svc = PlannerDomainService(
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

    compact = svc._compact_capabilities_for_llm(  # noqa: SLF001
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
        prompt="Show me Jennifer Gilstrap preferred name",
    )

    dim_keys = [row["column_key"] for row in compact["dimensions"]]
    assert "wt23.preferred_first_name" in dim_keys
    assert "wt23.preferred_last_name" in dim_keys


def test_score_domain_candidate_prefers_staff_columns_for_work_prompt() -> None:
    svc = PlannerDomainService(
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

    staff_score = svc._score_domain_candidate(  # noqa: SLF001
        prompt="Show me where Jennifer Gilstrap works",
        candidate=candidate,
        capabilities=capabilities,
        shortlisted_columns=staff_shortlist,
    )
    student_score = svc._score_domain_candidate(  # noqa: SLF001
        prompt="Show me where Jennifer Gilstrap works",
        candidate=candidate,
        capabilities=capabilities,
        shortlisted_columns=student_shortlist,
    )

    assert staff_score > student_score


def test_score_domain_candidate_work_prompt_penalizes_discipline_domain_name() -> None:
    svc = PlannerDomainService(
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

    staff_score = svc._score_domain_candidate(  # noqa: SLF001
        prompt="Show me where Jennifer Gilstrap works",
        candidate=staff_candidate,
        capabilities=capabilities,
        shortlisted_columns=shortlist,
    )
    discipline_score = svc._score_domain_candidate(  # noqa: SLF001
        prompt="Show me where Jennifer Gilstrap works",
        candidate=discipline_candidate,
        capabilities=capabilities,
        shortlisted_columns=shortlist,
    )

    assert staff_score > discipline_score


def test_score_domain_candidate_work_prompt_penalizes_student_domain_name() -> None:
    svc = PlannerDomainService(
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

    staff_score = svc._score_domain_candidate(  # noqa: SLF001
        prompt="Show me where Jennifer Gilstrap works",
        candidate=staff_candidate,
        capabilities=capabilities,
        shortlisted_columns=shortlist,
    )
    student_score = svc._score_domain_candidate(  # noqa: SLF001
        prompt="Show me where Jennifer Gilstrap works",
        candidate=student_candidate,
        capabilities=capabilities,
        shortlisted_columns=shortlist,
    )

    assert staff_score > student_score


def test_get_domain_candidates_expands_work_prompt_and_includes_staff_domain() -> None:
    class _CapturingDomainVector:
        def __init__(self) -> None:
            self.queries = []

        def search_domains(self, **kwargs):
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

    out = svc._get_domain_candidates(  # noqa: SLF001
        workspace_id="ws-1",
        vertical_norm="education",
        prompt="Show me where Jennifer Gilstrap works",
        provided_domain_id=None,
    )

    assert len(vector.queries) > 1
    assert any("staff assignments" in query.lower() for query in vector.queries)
    assert out[0]["domain_id"] == 5
    assert any(int(row.get("domain_id") or 0) == 6 for row in out)


def test_semantic_value_alias_constraints_feature_flag_off(monkeypatch) -> None:
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", False)
    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
        value_alias_resolver=_FakeValueAliasResolver(
            [{"concept_key": "COUNTRY", "canonical_value": "United States", "matched_alias": "US"}]
        ),
    )

    constraints = svc._semantic_value_alias_constraints(  # noqa: SLF001
        prompt="Show students not born in the US",
        vertical_norm="education",
    )
    assert constraints == []


def test_semantic_value_alias_constraints_feature_flag_on_merges_into_slot_hints(monkeypatch) -> None:
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)
    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
        value_alias_resolver=_FakeValueAliasResolver(
            [{"concept_key": "COUNTRY", "canonical_value": "United States", "matched_alias": "US"}]
        ),
    )

    constraints = svc._semantic_value_alias_constraints(  # noqa: SLF001
        prompt="Show students not born in the US",
        vertical_norm="education",
    )
    assert constraints and constraints[0]["value_hint"] == "United States"

    merged = svc._merge_slot_hints(  # noqa: SLF001
        prompt="Show students not born in the US",
        slot_payload={"intent": "list", "entity": "students", "constraints": [], "time_phrases": []},
        semantic_constraints=constraints,
    )
    assert any(str(item.get("value_hint") or "") == "United States" for item in merged["constraints"])
    assert "United States" in merged["subgroups"]


def test_semantic_value_alias_constraints_feature_flag_on_is_resilient_to_errors(monkeypatch) -> None:
    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)
    svc = PlannerDomainService(
        capabilities_service=_FakeCapabilitiesService(),
        domain_vector_service=_FakeDomainVectorService(),
        llm_client=_FakeLLM(),
        value_alias_resolver=_FakeValueAliasResolver(should_raise=True),
    )

    constraints = svc._semantic_value_alias_constraints(  # noqa: SLF001
        prompt="Show students not born in the US",
        vertical_norm="education",
    )
    assert constraints == []


def test_semester_indicator_resolution_uses_explicit_semantic_concept_keys(monkeypatch) -> None:
    class _FakeSql:
        def execute_query_mappings(self, query, params):
            del query, params
            return [
                {
                    "model_column_id": 9001,
                    "concept_key": "SEMESTER_SPRING_FLAG",
                    "semantic_type": "flag",
                    "priority_rank": 100,
                    "confidence_score": 0.99,
                },
                {
                    "model_column_id": 9002,
                    "concept_key": "SEMESTER_FALL_FLAG",
                    "semantic_type": "flag",
                    "priority_rank": 100,
                    "confidence_score": 0.99,
                },
                {
                    "model_column_id": 9003,
                    "concept_key": "SEMESTER_YEAR_ROUND_FLAG",
                    "semantic_type": "flag",
                    "priority_rank": 100,
                    "confidence_score": 0.99,
                },
            ]

    monkeypatch.setattr(planner_domain_service_module, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)
    monkeypatch.setattr(planner_domain_service_module, "MySQLSQLExecutor", lambda: _FakeSql())

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

    out = svc._resolve_semester_indicator_columns(  # noqa: SLF001
        workspace_id="ws-1",
        vertical_norm="education",
        capabilities=capabilities,
    )
    assert out["spring"] == "wt24.is_spring_block"
    assert out["fall"] == "wt24.is_fall_block"
    assert out["year_round"] == "wt24.is_year_round_block"


def test_validation_uses_full_capabilities_not_compact_subset() -> None:
    class _StudentCapsService:
        def get_domain_capabilities(self, *, workspace_id, user_id, domain_id, vertical_norm):
            del workspace_id, user_id, vertical_norm
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
    svc._compact_capabilities_for_llm = lambda **kwargs: {  # type: ignore[method-assign]
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
        def get_domain_capabilities(self, *, workspace_id, user_id, domain_id, vertical_norm):
            del workspace_id, user_id, vertical_norm
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
