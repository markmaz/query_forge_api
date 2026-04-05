"""Unit tests for app.services.planner_domain.semantic_integration_service."""
from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock

import app.services.planner_domain.semantic_integration_service as sem_mod
from app.services.planner_domain.semantic_integration_service import (
    SemanticIntegrationService,
)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_semantic_integration_service_can_be_constructed() -> None:
    svc = SemanticIntegrationService()
    assert svc is not None


def test_semantic_integration_service_accepts_injected_grounding_service() -> None:
    mock_grounding = MagicMock()
    svc = SemanticIntegrationService(semantic_grounding_service=mock_grounding)
    assert svc is not None


# ---------------------------------------------------------------------------
# resolve_alias_constraints
# ---------------------------------------------------------------------------


def test_resolve_alias_constraints_returns_empty_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(sem_mod, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", False)
    svc = SemanticIntegrationService()
    result = svc.resolve_alias_constraints(prompt="students born in US", vertical_norm="education")
    assert result == []


def test_resolve_alias_constraints_delegates_to_grounding_service(monkeypatch) -> None:
    monkeypatch.setattr(sem_mod, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)
    mock_grounding = MagicMock()
    mock_grounding.resolve_alias_constraints.return_value = [
        {"kind": "value", "text": "US", "op": "eq", "value_hint": "United States", "notes": None}
    ]
    svc = SemanticIntegrationService(semantic_grounding_service=mock_grounding)
    result = svc.resolve_alias_constraints(prompt="students born in US", vertical_norm="education")
    assert len(result) == 1
    assert result[0]["value_hint"] == "United States"
    mock_grounding.resolve_alias_constraints.assert_called_once()


def test_resolve_alias_constraints_deduplicates(monkeypatch) -> None:
    monkeypatch.setattr(sem_mod, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)
    constraint = {"kind": "value", "text": "US", "op": "eq", "value_hint": "United States", "notes": None}
    mock_grounding = MagicMock()
    mock_grounding.resolve_alias_constraints.return_value = [constraint, constraint]
    svc = SemanticIntegrationService(semantic_grounding_service=mock_grounding)
    result = svc.resolve_alias_constraints(prompt="test", vertical_norm="education")
    assert len(result) == 1


def test_resolve_alias_constraints_resilient_to_grounding_error(monkeypatch) -> None:
    monkeypatch.setattr(sem_mod, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)
    mock_grounding = MagicMock()
    mock_grounding.resolve_alias_constraints.side_effect = RuntimeError("boom")
    svc = SemanticIntegrationService(semantic_grounding_service=mock_grounding)
    result = svc.resolve_alias_constraints(prompt="test", vertical_norm="education")
    assert result == []


# ---------------------------------------------------------------------------
# resolve_semester_indicator_columns
# ---------------------------------------------------------------------------


def test_resolve_semester_indicator_columns_infers_spring_from_column_name(monkeypatch) -> None:
    monkeypatch.setattr(sem_mod, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", False)
    caps: Dict[str, Any] = {
        "filter_columns": [
            {
                "column_key": "wt1.is_spring_block",
                "column_name": "is_spring_block",
                "filterable": True,
                "semantic_type": "flag",
            }
        ],
        "dimensions": [],
        "time_columns": [],
    }
    svc = SemanticIntegrationService()
    result = svc.resolve_semester_indicator_columns(
        workspace_id="ws-1",
        vertical_norm="education",
        capabilities=caps,
    )
    assert result.get("spring") == "wt1.is_spring_block"


def test_resolve_semester_indicator_columns_infers_all_three(monkeypatch) -> None:
    monkeypatch.setattr(sem_mod, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", False)
    caps: Dict[str, Any] = {
        "filter_columns": [
            {"column_key": "wt1.is_spring", "column_name": "is_spring", "filterable": True},
            {"column_key": "wt1.is_fall", "column_name": "is_fall", "filterable": True},
            {"column_key": "wt1.is_year_round", "column_name": "is_year_round", "filterable": True},
        ],
        "dimensions": [],
        "time_columns": [],
    }
    svc = SemanticIntegrationService()
    result = svc.resolve_semester_indicator_columns(
        workspace_id="ws-1",
        vertical_norm="education",
        capabilities=caps,
    )
    assert result.get("spring") == "wt1.is_spring"
    assert result.get("fall") == "wt1.is_fall"
    assert result.get("year_round") == "wt1.is_year_round"


def test_resolve_semester_indicator_columns_uses_semantic_concepts(monkeypatch) -> None:
    monkeypatch.setattr(sem_mod, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)

    class _FakeSql:
        def execute_query_mappings(self, query, params):
            del params
            if "FROM workspace_column wc" in query:
                return [
                    {"workspace_column_id": 101, "concept_key": "SEMESTER_SPRING_FLAG"},
                ]
            return []

    monkeypatch.setattr(sem_mod, "ForgeMetaSQL", lambda: _FakeSql())

    caps: Dict[str, Any] = {
        "filter_columns": [
            {
                "column_key": "wt1.spring_flag",
                "column_name": "spring_flag",
                "filterable": True,
                "workspace_column_id": 101,
            }
        ],
        "dimensions": [],
        "time_columns": [],
    }
    svc = SemanticIntegrationService()
    result = svc.resolve_semester_indicator_columns(
        workspace_id="ws-1",
        vertical_norm="education",
        capabilities=caps,
    )
    assert result.get("spring") == "wt1.spring_flag"


def test_resolve_semester_indicator_columns_keeps_inferred_values_when_semantic_lookup_fails(monkeypatch) -> None:
    monkeypatch.setattr(sem_mod, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)

    class _FailingSql:
        def execute_query_mappings(self, query, params):
            del query, params
            raise RuntimeError("semantic lookup unavailable")

    monkeypatch.setattr(sem_mod, "ForgeMetaSQL", lambda: _FailingSql())

    caps: Dict[str, Any] = {
        "filter_columns": [
            {"column_key": "wt1.is_spring", "column_name": "is_spring", "filterable": True},
            {"column_key": "wt1.is_fall", "column_name": "is_fall", "filterable": True},
        ],
        "dimensions": [],
        "time_columns": [],
    }
    svc = SemanticIntegrationService()
    result = svc.resolve_semester_indicator_columns(
        workspace_id="ws-1",
        vertical_norm="education",
        capabilities=caps,
    )

    assert result == {
        "spring": "wt1.is_spring",
        "fall": "wt1.is_fall",
    }


# ---------------------------------------------------------------------------
# normalize_semantic_value_alias_filters
# ---------------------------------------------------------------------------


def test_normalize_semantic_value_alias_filters_disabled_returns_passthrough(monkeypatch) -> None:
    monkeypatch.setattr(sem_mod, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", False)
    plan = {"filters": [{"column_key": "wt1.race", "op": "=", "value": "hispanic"}]}
    svc = SemanticIntegrationService()
    result_plan, issues, debug = svc.normalize_semantic_value_alias_filters(
        plan_json=plan,
        workspace_id="ws-1",
        vertical_norm="education",
        capabilities={},
    )
    assert result_plan == plan
    assert issues == []
    assert debug["applied"] == 0


def test_normalize_semantic_value_alias_filters_empty_filters_passthrough(monkeypatch) -> None:
    monkeypatch.setattr(sem_mod, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)
    plan: Dict[str, Any] = {"filters": []}
    svc = SemanticIntegrationService()
    result_plan, issues, debug = svc.normalize_semantic_value_alias_filters(
        plan_json=plan,
        workspace_id="ws-1",
        vertical_norm="education",
        capabilities={},
    )
    assert issues == []
    assert debug["applied"] == 0


def test_normalize_semantic_value_alias_filters_applies_alias_map(monkeypatch) -> None:
    monkeypatch.setattr(sem_mod, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)

    class _FakeSql:
        def execute_query_mappings(self, query, params):
            del params
            if "FROM workspace_column wc" in query:
                return [{"workspace_column_id": 1004, "concept_key": "RACE_ETHNICITY"}]
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

    monkeypatch.setattr(sem_mod, "ForgeMetaSQL", lambda: _FakeSql())

    plan: Dict[str, Any] = {
        "filters": [{"column_key": "wt24.race_ethnicity", "op": "=", "value": "African American"}]
    }
    caps: Dict[str, Any] = {
        "filter_columns": [
            {
                "column_key": "wt24.race_ethnicity",
                "filterable": True,
                "workspace_column_id": 1004,
            }
        ]
    }
    svc = SemanticIntegrationService()
    result_plan, issues, debug = svc.normalize_semantic_value_alias_filters(
        plan_json=plan,
        workspace_id="ws-1",
        vertical_norm="education",
        capabilities=caps,
    )
    assert result_plan["filters"][0]["value"] == "Black"
    assert debug["applied"] == 1
    assert any("RACE_ETHNICITY" in issue for issue in issues)


def test_normalize_semantic_value_alias_filters_coerces_boolean(monkeypatch) -> None:
    monkeypatch.setattr(sem_mod, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)

    class _FakeSql:
        def execute_query_mappings(self, query, params):
            del params
            if "FROM workspace_column wc" in query:
                return [{"workspace_column_id": 2002, "concept_key": "IS_SCHOOL_DAY"}]
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

    monkeypatch.setattr(sem_mod, "ForgeMetaSQL", lambda: _FakeSql())

    plan: Dict[str, Any] = {
        "filters": [{"column_key": "wt24.is_school_day", "op": "=", "value": "off day"}]
    }
    caps: Dict[str, Any] = {
        "filter_columns": [
            {
                "column_key": "wt24.is_school_day",
                "data_type": "boolean",
                "semantic_type": "flag",
                "filterable": True,
                "workspace_column_id": 2002,
            }
        ]
    }
    svc = SemanticIntegrationService()
    result_plan, issues, debug = svc.normalize_semantic_value_alias_filters(
        plan_json=plan,
        workspace_id="ws-1",
        vertical_norm="generic",
        capabilities=caps,
    )
    assert result_plan["filters"][0]["value"] is False
    assert debug["applied"] == 1


def test_normalize_semantic_value_alias_filters_returns_passthrough_when_lookup_fails(monkeypatch) -> None:
    monkeypatch.setattr(sem_mod, "QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED", True)

    class _FailingSql:
        def execute_query_mappings(self, query, params):
            del query, params
            raise RuntimeError("semantic alias lookup unavailable")

    monkeypatch.setattr(sem_mod, "ForgeMetaSQL", lambda: _FailingSql())

    plan: Dict[str, Any] = {
        "filters": [{"column_key": "wt24.race_ethnicity", "op": "=", "value": "African American"}]
    }
    caps: Dict[str, Any] = {
        "filter_columns": [
            {
                "column_key": "wt24.race_ethnicity",
                "filterable": True,
                "workspace_column_id": 1004,
            }
        ]
    }
    svc = SemanticIntegrationService()
    result_plan, issues, debug = svc.normalize_semantic_value_alias_filters(
        plan_json=plan,
        workspace_id="ws-1",
        vertical_norm="education",
        capabilities=caps,
    )

    assert result_plan == plan
    assert issues == []
    assert debug["applied"] == 0
