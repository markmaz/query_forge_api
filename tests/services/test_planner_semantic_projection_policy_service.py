from __future__ import annotations

import pytest
from sqlalchemy.exc import SQLAlchemyError

import app.services.domain.planner_semantic_projection_policy_service as semantic_projection_policy_service
from app.services.domain.planner_semantic_projection_policy_service import PlannerSemanticProjectionPolicyService


def test_semantic_projection_policy_returns_student_default_projection() -> None:
    service = PlannerSemanticProjectionPolicyService()
    assert service.default_projection_concepts(entity="student") == [
        "STUDENT_ID",
        "STUDENT_FIRST_NAME",
        "FIRST_NAME",
        "STUDENT_LAST_NAME",
        "LAST_NAME",
    ]


def test_semantic_projection_policy_returns_student_name_filter_concepts() -> None:
    service = PlannerSemanticProjectionPolicyService()
    assert service.name_filter_concepts(entity="student") == [
        "STUDENT_LAST_NAME",
        "LAST_NAME",
        "STUDENT_FIRST_NAME",
        "FIRST_NAME",
    ]


def test_semantic_projection_policy_returns_student_name_concept_family() -> None:
    service = PlannerSemanticProjectionPolicyService()
    assert service.concept_family(concept_key="STUDENT_FIRST_NAME") == (
        "STUDENT_FIRST_NAME",
        "FIRST_NAME",
    )


def test_semantic_projection_policy_service_falls_back_on_expected_db_lookup_errors() -> None:
    class _FakeSQL:
        def execute_query_mappings(self, sql, params):
            del sql, params
            raise SQLAlchemyError("db unavailable")

    service = PlannerSemanticProjectionPolicyService(sql=_FakeSQL(), enable_db_lookup=True)

    assert service.default_projection_concepts(entity="student") == [
        "STUDENT_ID",
        "STUDENT_FIRST_NAME",
        "FIRST_NAME",
        "STUDENT_LAST_NAME",
        "LAST_NAME",
    ]


def test_semantic_projection_policy_service_surfaces_unexpected_policy_parse_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeSQL:
        def execute_query_mappings(self, sql, params):
            del sql, params
            return []

    def _boom(_value):
        raise AssertionError("unexpected policy parse bug")

    service = PlannerSemanticProjectionPolicyService(sql=_FakeSQL(), enable_db_lookup=True)
    monkeypatch.setattr(semantic_projection_policy_service, "_parse_policy_rule", _boom)

    with pytest.raises(AssertionError, match="unexpected policy parse bug"):
        service.default_projection_concepts(entity="student")
