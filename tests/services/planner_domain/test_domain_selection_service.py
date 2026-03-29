"""Unit tests for app.services.planner_domain.domain_selection_service."""
from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock

from app.services.planner_domain.domain_selection_service import DomainSelectionService


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_domain_selection_service_can_be_constructed() -> None:
    svc = DomainSelectionService(
        domain_vector=MagicMock(),
        capabilities_service=MagicMock(),
        rerank_policy_engine=MagicMock(),
        embedding_model_factory=MagicMock(),
        column_vector_factory=MagicMock(),
        semantic_grounding_factory=MagicMock(),
        semantic_alias_constraints_fn=MagicMock(),
    )
    assert svc is not None


# ---------------------------------------------------------------------------
# full_capabilities_for_execution
# ---------------------------------------------------------------------------


def _caps(
    *,
    dims: List[Dict[str, Any]] | None = None,
    time_cols: List[Dict[str, Any]] | None = None,
    metrics: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    return {
        "domain_id": 42,
        "domain_version": 3,
        "dimensions": dims or [],
        "time_columns": time_cols or [],
        "domain_metrics": metrics or [],
        "user_metrics": [],
        "overlay_metrics": [],
    }


def test_full_capabilities_for_execution_copies_all_sections() -> None:
    caps = _caps(
        dims=[{"column_key": "wt1.grade", "column_name": "grade"}],
        time_cols=[{"column_key": "wt1.school_year", "column_name": "school_year"}],
        metrics=[{"metric_key": "count"}],
    )
    result = DomainSelectionService.full_capabilities_for_execution(caps)
    assert result["domain_id"] == 42
    assert result["domain_version"] == 3
    assert len(result["dimensions"]) == 1
    assert len(result["time_columns"]) == 1
    assert len(result["domain_metrics"]) == 1


def test_full_capabilities_for_execution_filters_non_filterable() -> None:
    caps = _caps(
        dims=[
            {"column_key": "wt1.grade", "column_name": "grade"},
            {"column_key": "wt1.blob", "column_name": "blob", "filterable": False},
        ]
    )
    result = DomainSelectionService.full_capabilities_for_execution(caps)
    filter_keys = {r["column_key"] for r in result["filter_columns"]}
    assert "wt1.grade" in filter_keys
    assert "wt1.blob" not in filter_keys


def test_full_capabilities_for_execution_includes_time_in_filter_columns() -> None:
    caps = _caps(
        dims=[{"column_key": "wt1.grade", "column_name": "grade"}],
        time_cols=[{"column_key": "wt1.school_year", "column_name": "school_year"}],
    )
    result = DomainSelectionService.full_capabilities_for_execution(caps)
    filter_keys = {r["column_key"] for r in result["filter_columns"]}
    assert "wt1.school_year" in filter_keys
    assert "wt1.grade" in filter_keys


def test_full_capabilities_for_execution_empty_caps() -> None:
    result = DomainSelectionService.full_capabilities_for_execution({})
    assert result["domain_id"] == 0
    assert result["dimensions"] == []
    assert result["filter_columns"] == []


# ---------------------------------------------------------------------------
# _score_domain_candidate
# ---------------------------------------------------------------------------


def test_score_domain_candidate_base_formula() -> None:
    candidate: Dict[str, Any] = {"score": 0.8, "name": "student_demographics"}
    capabilities: Dict[str, Any] = {"dimensions": [{"col": f"d{i}"} for i in range(10)]}
    shortlisted: List[Dict[str, Any]] = [{"col": f"s{i}"} for i in range(5)]
    score = DomainSelectionService._score_domain_candidate(
        prompt="show students",
        candidate=candidate,
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
    )
    # vector_score * 0.65 + shortlist_ratio * 0.35 ≈ 0.52 + 0.175 = 0.695
    assert score > 0.5


def test_score_domain_candidate_penalizes_small_shortlist() -> None:
    candidate: Dict[str, Any] = {"score": 0.8, "name": "generic"}
    capabilities: Dict[str, Any] = {"dimensions": [{"col": f"d{i}"} for i in range(20)]}
    shortlisted: List[Dict[str, Any]] = [{"col": "a"}, {"col": "b"}]  # only 2, < 5
    score = DomainSelectionService._score_domain_candidate(
        prompt="show data",
        candidate=candidate,
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
    )
    # raw ≈ 0.52 + 0.035 = 0.555; penalty = -0.1
    assert score < 0.555


def test_score_domain_candidate_adm_boost() -> None:
    candidate: Dict[str, Any] = {"score": 0.5, "name": "adm_base"}
    capabilities: Dict[str, Any] = {
        "dimensions": [{"col": f"d{i}"} for i in range(10)],
        "domain_metrics": [{"metric_key": "normalized_adm", "label": "Average Daily Membership"}],
    }
    shortlisted: List[Dict[str, Any]] = [
        {"column_name": "normalized_adm", "column_key": "wt1.normalized_adm"},
    ]
    base_score = 0.5 * 0.65 + (1 / 10) * 0.35  # ~0.36
    score = DomainSelectionService._score_domain_candidate(
        prompt="average daily membership by school",
        candidate=candidate,
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
    )
    assert score > base_score + 0.1


def test_score_domain_candidate_staff_boost() -> None:
    candidate: Dict[str, Any] = {"score": 0.5, "name": "staff_assignments"}
    capabilities: Dict[str, Any] = {"dimensions": [{"col": f"d{i}"} for i in range(10)]}
    shortlisted: List[Dict[str, Any]] = [
        {"column_name": "staff_unique_id", "column_key": "wt1.staff_unique_id"},
        {"column_name": "position_title", "column_key": "wt1.position_title"},
    ]
    score = DomainSelectionService._score_domain_candidate(
        prompt="teacher at Lincoln school",
        candidate=candidate,
        capabilities=capabilities,
        shortlisted_columns=shortlisted,
    )
    base_score = 0.5 * 0.65 + (2 / 10) * 0.35  # ~0.395
    assert score > base_score


# ---------------------------------------------------------------------------
# _score_semantic_grounding_bundle
# ---------------------------------------------------------------------------


def _make_candidates(
    *,
    metrics: int = 0,
    dims: int = 0,
    filters: int = 0,
    time: int = 0,
    source: str = "",
) -> Any:
    class FakeCandidates:
        metric_candidates = [{}] * metrics
        dimension_candidates = [{}] * dims
        filter_candidates = [{}] * filters
        time_candidates = [{}] * time
        metadata = {"semantic_source": source}

    return FakeCandidates()


def _make_bundle(candidates: Any = None, alias_constraints: List[Any] | None = None) -> Any:
    class FakeBundle:
        pass

    b = FakeBundle()
    b.candidates = candidates
    b.alias_constraints = alias_constraints or []
    return b


def test_score_semantic_grounding_bundle_no_candidates_no_constraints() -> None:
    bundle = _make_bundle(candidates=None, alias_constraints=[])
    score = DomainSelectionService._score_semantic_grounding_bundle(
        prompt="show students", grounding_bundle=bundle
    )
    assert score == 0.0


def test_score_semantic_grounding_bundle_no_candidates_with_constraints() -> None:
    bundle = _make_bundle(candidates=None, alias_constraints=[{"something": "x"}])
    score = DomainSelectionService._score_semantic_grounding_bundle(
        prompt="show students", grounding_bundle=bundle
    )
    assert score == 0.02


def test_score_semantic_grounding_bundle_metric_candidates_boost() -> None:
    candidates = _make_candidates(metrics=2, dims=1)
    bundle = _make_bundle(candidates=candidates)
    score = DomainSelectionService._score_semantic_grounding_bundle(
        prompt="show metrics", grounding_bundle=bundle
    )
    # metric_count > 0: +0.06, dimension_count > 0: +0.05
    assert score >= 0.11


def test_score_semantic_grounding_bundle_capped_at_0_22() -> None:
    candidates = _make_candidates(metrics=5, dims=5, filters=5, time=5, source="semantic_index")
    bundle = _make_bundle(
        candidates=candidates,
        alias_constraints=[{"a": 1}, {"b": 2}, {"c": 3}],
    )
    score = DomainSelectionService._score_semantic_grounding_bundle(
        prompt="school year semester terms", grounding_bundle=bundle
    )
    assert score <= 0.22
