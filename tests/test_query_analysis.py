"""
tests/test_query_analysis.py

Tests for the inline query analysis feature:
  - analysis_utils (prompt building, hash, LLM call)
  - query_analysis_routes (caching, LLM unavailable, query not found)

Run with: pytest tests/test_query_analysis.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.skills.analysis_utils import (
    build_analysis_system_prompt,
    build_analysis_user_prompt,
    result_hash,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_rows():
    return [
        {"order_id": i, "revenue": float(100 * i), "region": "EMEA"}
        for i in range(1, 11)
    ]


# ---------------------------------------------------------------------------
# analysis_utils — prompt building
# ---------------------------------------------------------------------------


def test_system_prompt_contains_json_format():
    prompt = build_analysis_system_prompt()
    assert '"narrative"' in prompt
    assert '"highlights"' in prompt


def test_system_prompt_includes_hint():
    prompt = build_analysis_system_prompt(hint="Focus on outliers")
    assert "Focus on outliers" in prompt


def test_system_prompt_no_hint_clean():
    prompt = build_analysis_system_prompt(hint="")
    assert "Additional guidance" not in prompt


def test_user_prompt_includes_query_name(sample_rows):
    prompt = build_analysis_user_prompt(
        query_name="Revenue Report",
        column_names=["order_id", "revenue", "region"],
        row_count=10,
        rows=sample_rows,
    )
    assert "Revenue Report" in prompt


def test_user_prompt_includes_column_names(sample_rows):
    prompt = build_analysis_user_prompt(
        query_name="Q",
        column_names=["order_id", "revenue", "region"],
        row_count=10,
        rows=sample_rows,
    )
    assert "order_id" in prompt
    assert "revenue" in prompt


def test_user_prompt_truncates_sample():
    large_rows = [{"id": i, "val": i} for i in range(100)]
    prompt = build_analysis_user_prompt(
        query_name="Q",
        column_names=["id", "val"],
        row_count=100,
        rows=large_rows,
        max_sample_rows=30,
    )
    assert "30 of 100" in prompt


def test_user_prompt_no_truncation_note_when_under_limit(sample_rows):
    prompt = build_analysis_user_prompt(
        query_name="Q",
        column_names=["order_id", "revenue", "region"],
        row_count=10,
        rows=sample_rows,
        max_sample_rows=30,
    )
    assert "showing" not in prompt


def test_user_prompt_includes_previous_highlights(sample_rows):
    prompt = build_analysis_user_prompt(
        query_name="Q",
        column_names=["order_id", "revenue", "region"],
        row_count=10,
        rows=sample_rows,
        previous_highlights=["Revenue was $5K", "3 regions active"],
        previous_run_date="2024-01-01",
    )
    assert "Revenue was $5K" in prompt
    assert "2024-01-01" in prompt


# ---------------------------------------------------------------------------
# result_hash
# ---------------------------------------------------------------------------


def test_result_hash_is_16_chars(sample_rows):
    h = result_hash(sample_rows, 10)
    assert len(h) == 16


def test_result_hash_deterministic(sample_rows):
    h1 = result_hash(sample_rows, 10)
    h2 = result_hash(sample_rows, 10)
    assert h1 == h2


def test_result_hash_changes_with_different_data(sample_rows):
    h1 = result_hash(sample_rows, 10)
    different = [{"order_id": 99, "revenue": 9999.0, "region": "APAC"}]
    h2 = result_hash(different, 1)
    assert h1 != h2


def test_result_hash_changes_with_different_row_count(sample_rows):
    h1 = result_hash(sample_rows, 10)
    h2 = result_hash(sample_rows, 999)  # same rows, different total
    assert h1 != h2


def test_result_hash_uses_only_first_50_rows():
    rows_a = [{"id": i} for i in range(100)]
    rows_b = [{"id": i} for i in range(100)]
    # Same first 50, different last 50
    rows_b[75]["id"] = 9999
    # Hashes should be equal since only first 50 are compared
    assert result_hash(rows_a, 100) == result_hash(rows_b, 100)


# ---------------------------------------------------------------------------
# Route — POST /api/v1/queries/<id>/analyze
# ---------------------------------------------------------------------------


def test_analyze_returns_narrative_and_highlights(client, auth_headers):
    mock_analysis = {
        "narrative": "Revenue grew steadily.",
        "highlights": ["EMEA leads at 62%", "10 rows total"],
        "comparison": None,
    }
    with patch("app.routes.query_analysis_routes._check_llm_available", return_value=True), \
         patch("app.routes.query_analysis_routes._run_query", return_value={
             "rows": [{"id": 1}],
             "query_name": "Test Query",
             "column_names": ["id"],
             "row_count": 1,
         }), \
         patch("app.routes.query_analysis_routes.call_analysis_llm", return_value=mock_analysis), \
         patch("app.routes.query_analysis_routes._get_cache", return_value=None), \
         patch("app.routes.query_analysis_routes._set_cache"):
        res = client.post(
            "/api/v1/queries/1/analyze",
            json={"prompt_hint": ""},
            headers=auth_headers,
        )

    assert res.status_code == 200
    data = res.get_json()
    assert "narrative" in data
    assert "highlights" in data
    assert data["cached"] is False


def test_analyze_returns_503_when_no_llm(client, auth_headers):
    with patch("app.routes.query_analysis_routes._check_llm_available", return_value=False):
        res = client.post(
            "/api/v1/queries/1/analyze",
            json={},
            headers=auth_headers,
        )
    assert res.status_code == 503
    assert "LLM" in res.get_json().get("error", "")


def test_analyze_returns_404_for_missing_query(client, auth_headers):
    with patch("app.routes.query_analysis_routes._check_llm_available", return_value=True), \
         patch("app.routes.query_analysis_routes._run_query", side_effect=ValueError("Query 999 not found")), \
         patch("app.routes.query_analysis_routes._get_cache", return_value=None):
        res = client.post(
            "/api/v1/queries/999/analyze",
            json={},
            headers=auth_headers,
        )
    assert res.status_code == 404


def test_analyze_returns_cached_result(client, auth_headers):
    cached_data = {
        "narrative": "Cached narrative.",
        "highlights": ["cached highlight"],
        "row_count": 5,
        "result_hash": "abc123",
    }
    with patch("app.routes.query_analysis_routes._check_llm_available", return_value=True), \
         patch("app.routes.query_analysis_routes._get_cache", return_value=cached_data):
        res = client.post(
            "/api/v1/queries/1/analyze",
            json={"result_hash": "abc123"},
            headers=auth_headers,
        )

    assert res.status_code == 200
    data = res.get_json()
    assert data["cached"] is True
    assert data["narrative"] == "Cached narrative."


def test_analyze_returns_502_on_llm_failure(client, auth_headers):
    with patch("app.routes.query_analysis_routes._check_llm_available", return_value=True), \
         patch("app.routes.query_analysis_routes._run_query", return_value={
             "rows": [], "query_name": "Q", "column_names": [], "row_count": 0,
         }), \
         patch("app.routes.query_analysis_routes._get_cache", return_value=None), \
         patch("app.routes.query_analysis_routes.call_analysis_llm",
               side_effect=RuntimeError("LLM timeout")):
        res = client.post(
            "/api/v1/queries/1/analyze",
            json={},
            headers=auth_headers,
        )
    assert res.status_code == 502


def test_analyze_includes_prompt_hint_in_call(client, auth_headers):
    with patch("app.routes.query_analysis_routes._check_llm_available", return_value=True), \
         patch("app.routes.query_analysis_routes._run_query", return_value={
             "rows": [{"id": 1}], "query_name": "Q", "column_names": ["id"], "row_count": 1,
         }), \
         patch("app.routes.query_analysis_routes._get_cache", return_value=None), \
         patch("app.routes.query_analysis_routes._set_cache"), \
         patch("app.routes.query_analysis_routes.call_analysis_llm",
               return_value={"narrative": "N", "highlights": ["H"], "comparison": None}) as mock_llm, \
         patch("app.routes.query_analysis_routes.build_analysis_system_prompt",
               wraps=build_analysis_system_prompt) as mock_prompt:
        client.post(
            "/api/v1/queries/1/analyze",
            json={"prompt_hint": "Focus on anomalies"},
            headers=auth_headers,
        )
    mock_prompt.assert_called_once_with(hint="Focus on anomalies")
