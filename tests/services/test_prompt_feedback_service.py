from __future__ import annotations

from datetime import datetime

import pytest

from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import ExecuteResult
from app.services.prompt_feedback_service import PromptFeedbackService
from tests._support.fakes import FakeSQLExecutor


def _row(*, feedback_id: int, vote: str) -> dict:
    return {
        "id": feedback_id,
        "vote": vote,
        "created_at": datetime(2026, 1, 1, 12, 0, 0),
        "updated_at": datetime(2026, 1, 1, 12, 1, 0),
    }


def test_save_feedback_creates_with_trace_id() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [],
        [_row(feedback_id=11, vote="up")],
    ]
    sql.insert_responses = [ExecuteResult(rowcount=1, lastrowid=11)]

    svc = PromptFeedbackService(sql=sql, max_payload_bytes=1024)
    out = svc.save_feedback(
        workspace_id="ws-1",
        user_id="user-1",
        trace_id="trace-1",
        vote="up",
        normalized_prompt="normalized",
        prompt_text="prompt",
        response_json={"answer": "ok"},
        meta={"model": "gpt"},
    )

    assert out.id == 11
    assert out.vote == "up"
    assert out.created is True
    assert "ON DUPLICATE KEY UPDATE" in sql.insert_calls[0].query
    assert sql.insert_calls[0].params["trace_id"] == "trace-1"


def test_save_feedback_updates_existing_on_same_workspace_user_trace() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [{"id": 7}],
        [_row(feedback_id=7, vote="down")],
    ]
    sql.insert_responses = [ExecuteResult(rowcount=2, lastrowid=7)]

    svc = PromptFeedbackService(sql=sql, max_payload_bytes=1024)
    out = svc.save_feedback(
        workspace_id="ws-1",
        user_id="user-1",
        trace_id="trace-1",
        vote="down",
        normalized_prompt="normalized",
        prompt_text="prompt",
        response_json={"answer": "updated"},
        meta={"intent": "list"},
    )

    assert out.id == 7
    assert out.vote == "down"
    assert out.created is False
    assert len(sql.insert_calls) == 1


def test_save_feedback_allows_multiple_rows_with_null_trace() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [_row(feedback_id=100, vote="up")],
        [_row(feedback_id=101, vote="down")],
    ]
    sql.insert_responses = [
        ExecuteResult(rowcount=1, lastrowid=100),
        ExecuteResult(rowcount=1, lastrowid=101),
    ]

    svc = PromptFeedbackService(sql=sql, max_payload_bytes=1024)
    first = svc.save_feedback(
        workspace_id="ws-1",
        user_id="user-1",
        vote="up",
        response_json={"run": 1},
    )
    second = svc.save_feedback(
        workspace_id="ws-1",
        user_id="user-1",
        vote="down",
        response_json={"run": 2},
    )

    assert first.id == 100
    assert second.id == 101
    assert first.created is True and second.created is True
    assert "ON DUPLICATE KEY UPDATE" not in sql.insert_calls[0].query
    assert "ON DUPLICATE KEY UPDATE" not in sql.insert_calls[1].query


def test_save_feedback_rejects_large_response_payload() -> None:
    sql = FakeSQLExecutor()
    svc = PromptFeedbackService(sql=sql, max_payload_bytes=10)
    with pytest.raises(ServiceError, match="response_json exceeds max size"):
        svc.save_feedback(
            workspace_id="ws-1",
            user_id="user-1",
            vote="up",
            response_json={"text": "this is too large"},
        )
