from __future__ import annotations

import json
import pytest

from app.services.chat.education_fewshot_service import EducationFewshotService
from tests._support.fakes import FakeForgeQueryPort


def test_fewshot_uses_only_upvoted_education_feedback() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
                {
                    "normalized_prompt": "Show me students by school",
                    "prompt_text": "show students by school",
                    "response_json": {"route": "plan_domain"},
                },
            {
                "normalized_prompt": "Tell me a joke",
                "prompt_text": "Tell me a joke",
                "response_json": {"mode": "chat"},
            },
            {
                "normalized_prompt": "Count enrollment by district",
                "prompt_text": "Count enrollment by district",
                "response_json": json.dumps({"route": "plan_domain"}),
            },
        ]
    ]

    svc = EducationFewshotService(sql=sql, limit=5, scan_limit=20, cache_seconds=0)
    out = svc.get_examples(workspace_id="ws-1", user_id="u1")
    assert out == [
        "Show me students by school",
        "Count enrollment by district",
    ]


def test_fewshot_dedupes_and_caches() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "normalized_prompt": "Show me students by school",
                "prompt_text": None,
                "response_json": {"mode": "education_pipeline"},
            },
            {
                "normalized_prompt": "show me students by school",
                "prompt_text": None,
                "response_json": {"mode": "education_pipeline"},
            },
        ]
    ]
    svc = EducationFewshotService(sql=sql, limit=5, scan_limit=20, cache_seconds=60)
    first = svc.get_examples(workspace_id="ws-1", user_id="u1")
    second = svc.get_examples(workspace_id="ws-1", user_id="u1")
    assert first == ["Show me students by school"]
    assert second == ["Show me students by school"]
    # Cached second call should not execute another SQL query.
    assert len(sql.query_mappings_calls) == 1


def test_fewshot_fetch_rows_falls_back_on_expected_runtime_errors() -> None:
    class _SQL:
        def execute_query_mappings(self, query, params):
            del query, params
            raise RuntimeError("db unavailable")

    svc = EducationFewshotService(sql=_SQL(), cache_seconds=0)

    assert svc.get_examples(workspace_id="ws-1", user_id="u1") == []


def test_fewshot_fetch_rows_surfaces_unexpected_errors() -> None:
    class _SQL:
        def execute_query_mappings(self, query, params):
            del query, params
            raise AssertionError("unexpected fewshot bug")

    svc = EducationFewshotService(sql=_SQL(), cache_seconds=0)

    with pytest.raises(AssertionError, match="unexpected fewshot bug"):
        svc.get_examples(workspace_id="ws-1", user_id="u1")
