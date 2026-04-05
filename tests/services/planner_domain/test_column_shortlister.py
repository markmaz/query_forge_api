"""Unit tests for app.services.planner_domain.column_shortlister."""
from __future__ import annotations

import pytest
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.services.planner_domain.column_shortlister import shortlist_columns_for_domain


def _capabilities():
    return {
        "dimensions": [
            {
                "column_key": "wt20.school_name",
                "column_name": "school_name",
                "workspace_table_id": 20,
            },
            {
                "column_key": "wt20.county_name",
                "column_name": "county_name",
                "workspace_table_id": 20,
            },
            {
                "column_key": "wt24.student_unique_id",
                "column_name": "student_unique_id",
                "workspace_table_id": 24,
            },
        ],
        "time_columns": [],
    }


class _FakeEmbeddingModel:
    def encode(self, texts, *, normalize=True):
        del texts, normalize
        return [[0.1, 0.2, 0.3]]


class _FakeHit:
    def __init__(self, *, workspace_table_id: int, column_name: str, score: float) -> None:
        self.payload = {
            "workspace_table_id": workspace_table_id,
            "column_name": column_name,
        }
        self.score = score


class _FakeColumnVector:
    def search(self, **kwargs):
        del kwargs
        return [
            _FakeHit(workspace_table_id=20, column_name="school_name", score=0.9),
            _FakeHit(workspace_table_id=24, column_name="student_unique_id", score=0.8),
        ]


def test_shortlist_columns_for_domain_prefers_vector_results():
    out = shortlist_columns_for_domain(
        prompt="show students by school",
        workspace_id="ws-1",
        capabilities=_capabilities(),
        embedding_model_factory=lambda: _FakeEmbeddingModel(),
        column_vector_factory=lambda: _FakeColumnVector(),
    )

    keys = [row["column_key"] for row in out]
    assert keys[0] == "wt20.school_name"
    assert "wt24.student_unique_id" in keys


def test_shortlist_columns_for_domain_falls_back_on_embedding_failures():
    class _FailingEmbeddingModel:
        def encode(self, texts, *, normalize=True):
            del texts, normalize
            raise RuntimeError("embedding unavailable")

    out = shortlist_columns_for_domain(
        prompt="show students by school",
        workspace_id="ws-1",
        capabilities=_capabilities(),
        embedding_model_factory=lambda: _FailingEmbeddingModel(),
        column_vector_factory=lambda: _FakeColumnVector(),
    )

    keys = {row["column_key"] for row in out}
    assert "wt20.school_name" in keys
    assert "wt24.student_unique_id" in keys


def test_shortlist_columns_for_domain_surfaces_unexpected_embedding_failures():
    class _FailingEmbeddingModel:
        def encode(self, texts, *, normalize=True):
            del texts, normalize
            raise AssertionError("unexpected embedding failure")

    with pytest.raises(AssertionError, match="unexpected embedding failure"):
        shortlist_columns_for_domain(
            prompt="show students by school",
            workspace_id="ws-1",
            capabilities=_capabilities(),
            embedding_model_factory=lambda: _FailingEmbeddingModel(),
            column_vector_factory=lambda: _FakeColumnVector(),
        )


def test_shortlist_columns_for_domain_falls_back_on_vector_failures():
    class _FailingColumnVector:
        def search(self, **kwargs):
            del kwargs
            raise UnexpectedResponse(
                status_code=503,
                reason_phrase="service unavailable",
                headers={},
                content=b"down",
            )

    out = shortlist_columns_for_domain(
        prompt="show students by school",
        workspace_id="ws-1",
        capabilities=_capabilities(),
        embedding_model_factory=lambda: _FakeEmbeddingModel(),
        column_vector_factory=lambda: _FailingColumnVector(),
    )

    keys = {row["column_key"] for row in out}
    assert "wt20.school_name" in keys
    assert "wt24.student_unique_id" in keys


def test_shortlist_columns_for_domain_surfaces_unexpected_vector_failures():
    class _FailingColumnVector:
        def search(self, **kwargs):
            del kwargs
            raise AssertionError("unexpected vector failure")

    with pytest.raises(AssertionError, match="unexpected vector failure"):
        shortlist_columns_for_domain(
            prompt="show students by school",
            workspace_id="ws-1",
            capabilities=_capabilities(),
            embedding_model_factory=lambda: _FakeEmbeddingModel(),
            column_vector_factory=lambda: _FailingColumnVector(),
        )


def test_shortlist_columns_for_domain_falls_back_on_qdrant_response_handling_failures():
    class _FailingColumnVector:
        def search(self, **kwargs):
            del kwargs
            raise ResponseHandlingException(ValueError("connection reset"))

    out = shortlist_columns_for_domain(
        prompt="show students by school",
        workspace_id="ws-1",
        capabilities=_capabilities(),
        embedding_model_factory=lambda: _FakeEmbeddingModel(),
        column_vector_factory=lambda: _FailingColumnVector(),
    )

    keys = {row["column_key"] for row in out}
    assert "wt20.school_name" in keys
    assert "wt24.student_unique_id" in keys
