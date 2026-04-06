from __future__ import annotations

import pytest

from app.services.planner_llm.service import PlannerLLMConstraints, PlannerLLMService


class _FakeRetriever:
    def retrieve(self, *, workspace_id, vertical, normalized_prompt, constraints):
        del workspace_id, vertical, normalized_prompt, constraints
        return {
            "domains": [
                {
                    "domain_id": 10,
                    "name": "Enrollment",
                    "tables": ["fct_student_school_association", "dim_school"],
                },
                {
                    "domain_id": 11,
                    "name": "Staff & Assignments",
                    "tables": ["fct_staff_school_association", "dim_school"],
                },
                {
                    "domain_id": 12,
                    "name": "Schools",
                    "tables": ["dim_school"],
                },
            ],
            "concepts": [{"concept_key": "STUDENTS_PER_TEACHER", "semantic_type": "metric"}],
            "columns": [
                {
                    "column_key": "wt20.county_fips_code",
                    "workspace_table_id": 20,
                    "model_column_id": 286,
                    "column_name": "county_fips_code",
                    "table": "dim_school",
                    "data_type": "int",
                    "semantic_type_strict": "dimension",
                    "sample_values": [51031],
                    "pii_flag": False,
                },
                {
                    "column_key": "wt61.k_student",
                    "workspace_table_id": 61,
                    "model_column_id": 1064,
                    "column_name": "k_student",
                    "table": "fct_student_school_association",
                    "data_type": "bigint",
                    "semantic_type_strict": "identifier",
                    "sample_values": [123],
                    "pii_flag": False,
                },
                {
                    "column_key": "wt30.k_staff_school_association",
                    "workspace_table_id": 30,
                    "model_column_id": 740,
                    "column_name": "k_staff_school_association",
                    "table": "fct_staff_school_association",
                    "data_type": "bigint",
                    "semantic_type_strict": "identifier",
                    "sample_values": [55],
                    "pii_flag": False,
                },
            ],
        }


class _FakeLLM:
    def chat_json_with_trace(self, **kwargs):
        del kwargs
        return {
            "parsed": {
                "intent": "aggregate",
                "grain": {"entity": "school", "time_grain": None},
                "selects": {
                    "metrics": [
                        {
                            "metric_ref": "column:wt20.county_fips_code",
                            "kind": "numeric",
                            "agg": "avg",
                            "label": "bad_metric",
                        }
                    ],
                    "dimensions": [{"column_key": "wt20.county_fips_code", "label": "county"}],
                },
                "filters": [],
                "domains": [10],
                "aggregation": {
                    "group_by": ["wt20.county_fips_code"],
                    "metrics": [
                        {
                            "metric_ref": "column:wt20.county_fips_code",
                            "agg": "avg",
                            "label": "bad_metric",
                        }
                    ],
                },
                "derived_metrics": [
                    {
                        "name": "students_per_teacher_ratio",
                        "kind": "ratio",
                        "numerator": {"column_key": "wt61.k_student", "agg": "count_distinct"},
                        "denominator": {"column_key": "wt30.k_staff_school_association", "agg": "count_distinct"},
                        "safe_divide": True,
                    }
                ],
            },
            "content": "{}",
            "raw_text": "{}",
        }


class _FakeCache:
    def get_registry_version(self, *, vertical):
        del vertical
        return "v1"

    def build_cache_key(self, **kwargs):
        del kwargs
        return "cache-key"

    def get(self, *, cache_key, registry_version):
        del cache_key, registry_version
        return None

    def set(self, **kwargs):
        del kwargs


class _ExpectedFailingCache(_FakeCache):
    def set(self, **kwargs):
        del kwargs
        raise RuntimeError("cache unavailable")


class _UnexpectedFailingCache(_FakeCache):
    def set(self, **kwargs):
        del kwargs
        raise AssertionError("unexpected cache write failure")


def test_golden_students_per_teacher_by_county_uses_derived_ratio_and_repairs_domains() -> None:
    svc = PlannerLLMService(
        retriever=_FakeRetriever(),
        llm_client=_FakeLLM(),
        cache=_FakeCache(),
    )
    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "prompt": "students per teacher by county",
            "vertical": "education",
            "constraints": PlannerLLMConstraints(max_domains=3).model_dump(mode="json"),
            "debug": True,
        }
    )

    assert out["validation"]["is_valid"] is True
    assert out["plan_json"]["selects"]["metrics"][0]["metric_ref"] == "derived:students_per_teacher_ratio"
    assert "wt20.county_fips_code" in (out["plan_json"]["aggregation"]["group_by"] or [])
    derived = out["plan_json"]["derived_metrics"][0]
    assert derived["numerator"]["agg"] == "count_distinct"
    assert derived["numerator"]["column_key"] == "wt61.k_student"
    assert derived["denominator"]["agg"] == "count_distinct"
    assert derived["denominator"]["column_key"] == "wt30.k_staff_school_association"
    assert {10, 11}.issubset(set(out["plan_json"]["domains"]))

    aggs = out["sql_json"]["aggs"]["metrics"]
    expr_metric = next((m for m in aggs if m.get("fn") == "expr"), None)
    assert expr_metric is not None
    assert expr_metric["expr"]["numerator"]["fn"] == "count_distinct"
    assert expr_metric["expr"]["numerator"]["field"]["columnName"] == "k_student"
    assert expr_metric["expr"]["denominator"]["fn"] == "count_distinct"
    assert expr_metric["expr"]["denominator"]["field"]["columnName"] == "k_staff_school_association"


def test_plan_survives_expected_cache_write_failures() -> None:
    svc = PlannerLLMService(
        retriever=_FakeRetriever(),
        llm_client=_FakeLLM(),
        cache=_ExpectedFailingCache(),
    )

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "prompt": "students per teacher by county",
            "vertical": "education",
            "constraints": PlannerLLMConstraints(max_domains=3).model_dump(mode="json"),
            "debug": False,
        }
    )

    assert out["validation"]["is_valid"] is True
    assert out["cache"]["hit"] is False


def test_plan_surfaces_unexpected_cache_write_failures() -> None:
    svc = PlannerLLMService(
        retriever=_FakeRetriever(),
        llm_client=_FakeLLM(),
        cache=_UnexpectedFailingCache(),
    )

    with pytest.raises(AssertionError, match="unexpected cache write failure"):
        svc.plan(
            {
                "workspace_id": "ws-1",
                "prompt": "students per teacher by county",
                "vertical": "education",
                "constraints": PlannerLLMConstraints(max_domains=3).model_dump(mode="json"),
                "debug": False,
            }
        )
