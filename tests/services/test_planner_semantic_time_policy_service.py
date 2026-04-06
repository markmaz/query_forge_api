from __future__ import annotations

import pytest
from sqlalchemy.exc import SQLAlchemyError

import app.services.domain.planner_semantic_time_policy_service as semantic_time_policy_service
from app.services.domain.planner_semantic_time_policy_service import PlannerSemanticTimePolicyService


def test_semantic_time_policy_prefers_school_year_for_enrollment() -> None:
    service = PlannerSemanticTimePolicyService()

    out = service.select_preferred_time_column(
        domain_hint="enrollment",
        mapped_columns_for_time_concept=[
            {"model_column_id": 2, "column_name": "year", "concept_key": "SCHOOL_YEAR", "final_score": 3.8},
            {"model_column_id": 1, "column_name": "school_year", "concept_key": "SCHOOL_YEAR", "final_score": 3.7},
        ],
    )

    assert out["model_column_id"] == 1


def test_semantic_time_policy_falls_back_to_generic_rule() -> None:
    service = PlannerSemanticTimePolicyService()

    out = service.select_preferred_time_column(
        domain_hint="unknown",
        mapped_columns_for_time_concept=[
            {"model_column_id": 2, "column_name": "calendar_year", "concept_key": "CALENDAR_YEAR", "final_score": 3.9},
            {"model_column_id": 1, "column_name": "year", "concept_key": "SCHOOL_YEAR", "final_score": 3.5},
        ],
    )

    assert out["model_column_id"] == 1


def test_semantic_time_policy_service_falls_back_on_expected_db_lookup_errors() -> None:
    class _FakeSQL:
        def execute_query_mappings(self, sql, params):
            del sql, params
            raise SQLAlchemyError("db unavailable")

    service = PlannerSemanticTimePolicyService(sql=_FakeSQL(), enable_db_lookup=True)

    out = service.select_preferred_time_column(
        domain_hint="enrollment",
        mapped_columns_for_time_concept=[
            {"model_column_id": 2, "column_name": "year", "concept_key": "SCHOOL_YEAR", "final_score": 3.8},
            {"model_column_id": 1, "column_name": "school_year", "concept_key": "SCHOOL_YEAR", "final_score": 3.7},
        ],
    )

    assert out["model_column_id"] == 1


def test_semantic_time_policy_service_surfaces_unexpected_policy_parse_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeSQL:
        def execute_query_mappings(self, sql, params):
            del sql, params
            return []

    def _boom(_value):
        raise AssertionError("unexpected policy parse bug")

    service = PlannerSemanticTimePolicyService(sql=_FakeSQL(), enable_db_lookup=True)
    monkeypatch.setattr(semantic_time_policy_service, "_parse_policy_rule", _boom)

    with pytest.raises(AssertionError, match="unexpected policy parse bug"):
        service.select_preferred_time_column(
            domain_hint="enrollment",
            mapped_columns_for_time_concept=[
                {"model_column_id": 1, "column_name": "school_year", "concept_key": "SCHOOL_YEAR", "final_score": 3.7},
            ],
        )
