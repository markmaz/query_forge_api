from __future__ import annotations

import pytest
from sqlalchemy.exc import SQLAlchemyError

import app.services.domain.planner_semantic_join_policy_service as semantic_join_policy_service
from app.services.domain.planner_semantic_join_policy_service import PlannerSemanticJoinPolicyService


def test_semantic_join_policy_prefers_dim_school_school_name_for_school_filters() -> None:
    service = PlannerSemanticJoinPolicyService()

    dim_school_rank = service.filter_column_rank(
        concept_key="SCHOOL_NAME",
        row={
            "__selected__": False,
            "table_name": "dim_school",
            "column_name": "school_name",
            "effective_weight": 1.2,
            "model_column_id": 10,
        },
    )
    fact_rank = service.filter_column_rank(
        concept_key="SCHOOL_NAME",
        row={
            "__selected__": False,
            "table_name": "fct_student_school_association",
            "column_name": "school_name",
            "effective_weight": 1.3,
            "model_column_id": 11,
        },
    )

    assert dim_school_rank < fact_rank


def test_semantic_join_policy_adds_student_school_join() -> None:
    service = PlannerSemanticJoinPolicyService()

    out = service.ensure_required_join_plan(
        join_plan={},
        selected_tables=["dim_student"],
        present_filter_concept_keys=["SCHOOL_NAME"],
        required_join_tables=["dim_school"],
    )

    assert out["primary_table"] == "dim_student"
    assert out["joins"] == [
        {
            "table": "dim_school",
            "on": [{"concept_key": "SCHOOL_ID", "op": "=", "value": "SCHOOL_ID"}],
        }
    ]


def test_semantic_join_policy_service_falls_back_on_expected_db_lookup_errors() -> None:
    class _FakeSQL:
        def execute_query_mappings(self, sql, params):
            del sql, params
            raise SQLAlchemyError("db unavailable")

    service = PlannerSemanticJoinPolicyService(sql=_FakeSQL(), enable_db_lookup=True)

    out = service.ensure_required_join_plan(
        join_plan={},
        selected_tables=["dim_student"],
        present_filter_concept_keys=["SCHOOL_NAME"],
        required_join_tables=["dim_school"],
    )

    assert out["primary_table"] == "dim_student"


def test_semantic_join_policy_service_surfaces_unexpected_policy_parse_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeSQL:
        def execute_query_mappings(self, sql, params):
            del sql, params
            return []

    def _boom(_value):
        raise AssertionError("unexpected policy parse bug")

    service = PlannerSemanticJoinPolicyService(sql=_FakeSQL(), enable_db_lookup=True)
    monkeypatch.setattr(semantic_join_policy_service, "_parse_policy_rule", _boom)

    with pytest.raises(AssertionError, match="unexpected policy parse bug"):
        service.ensure_required_join_plan(
            join_plan={},
            selected_tables=["dim_student"],
            present_filter_concept_keys=["SCHOOL_NAME"],
            required_join_tables=["dim_school"],
        )
