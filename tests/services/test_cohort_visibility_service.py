from __future__ import annotations

from datetime import datetime

from app.services.query_tree.cohort_visibility_service import CohortVisibilityService
from tests._support.fakes import FakeSQLExecutor


def test_cohort_visibility_filters_and_marks_shared() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [
        [
            {
                "query_id": "q1",
                "workspace_id": "ws-1",
                "owner_user_id": "user-1",
                "title": "My Cohort",
                "sql_json": {"meta": {"tool": "cohort_builder"}, "prompt": " Root prompt "},
                "updated_at": datetime(2024, 1, 1, 12, 0, 0),
                "can_edit": 0,
                "has_share": 0,
            },
            {
                "query_id": "q2",
                "workspace_id": "ws-1",
                "owner_user_id": "user-2",
                "title": "Shared Cohort",
                "sql_json": {"meta": {"tool": "cohort_builder", "prompt": "Meta prompt"}},
                "updated_at": datetime(2024, 1, 2, 12, 0, 0),
                "can_edit": 1,
                "has_share": 1,
            },
            {
                "query_id": "q3",
                "workspace_id": "ws-1",
                "owner_user_id": "user-1",
                "title": "Other Tool",
                "sql_json": {"meta": {"tool": "no_code_builder"}},
                "updated_at": datetime(2024, 1, 3, 12, 0, 0),
                "can_edit": 0,
                "has_share": 0,
            },
        ]
    ]

    svc = CohortVisibilityService(workspace_id="ws-1", user_id="user-1", sql=fake)
    result = svc.list_visible()

    cohorts = result["cohorts"]
    assert result["hasShared"] is True
    assert [c["queryId"] for c in cohorts] == ["q1", "q2"]

    shared = next(c for c in cohorts if c["queryId"] == "q2")
    assert shared["accessVia"] == "share"
    assert shared["canEdit"] is True
    assert shared["prompt"] == "Meta prompt"

    owned = next(c for c in cohorts if c["queryId"] == "q1")
    assert owned["prompt"] == "Root prompt"
    assert owned["updatedAt"] == "2024-01-01T12:00:00"

    params = fake.query_mappings_calls[0].params or {}
    assert params["ws"] == "ws-1"
    assert params["uid"] == "user-1"


def test_prompt_from_sql_json_missing_or_invalid() -> None:
    svc = CohortVisibilityService(workspace_id="ws-1", user_id="user-1", sql=FakeSQLExecutor())

    assert svc._prompt_from_sql_json("not json") is None
    assert svc._prompt_from_sql_json({"meta": {"tool": "cohort_builder"}}) is None
    assert svc._prompt_from_sql_json({"input": {"prompt": "  hi "}}) == "hi"
