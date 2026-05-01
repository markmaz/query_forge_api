from __future__ import annotations

from datetime import datetime

import pytest

from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeExecResult
from app.services.prompt_feedback_service import PromptFeedbackService
from tests._support.fakes import FakeForgeQueryPort


def _row(*, feedback_id: int, vote: str) -> dict:
    return {
        "id": feedback_id,
        "vote": vote,
        "created_at": datetime(2026, 1, 1, 12, 0, 0),
        "updated_at": datetime(2026, 1, 1, 12, 1, 0),
    }


def test_save_feedback_creates_with_trace_id() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [],
        [_row(feedback_id=11, vote="up")],
    ]
    sql.insert_responses = [ForgeExecResult(rowcount=1, lastrowid=11)]

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
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"id": 7}],
        [_row(feedback_id=7, vote="down")],
    ]
    sql.insert_responses = [ForgeExecResult(rowcount=2, lastrowid=7)]

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
    assert out.status == "analysis_pending"
    assert out.created is False
    assert len(sql.insert_calls) == 1


def test_save_feedback_allows_multiple_rows_with_null_trace() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [_row(feedback_id=100, vote="up")],
        [_row(feedback_id=101, vote="down")],
    ]
    sql.insert_responses = [
        ForgeExecResult(rowcount=1, lastrowid=100),
        ForgeExecResult(rowcount=1, lastrowid=101),
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
    assert first.status == "recorded"
    assert second.status == "analysis_pending"
    assert first.created is True and second.created is True
    assert "ON DUPLICATE KEY UPDATE" not in sql.insert_calls[0].query
    assert "ON DUPLICATE KEY UPDATE" not in sql.insert_calls[1].query


def test_save_feedback_merges_feedback_comment_into_reserved_meta_key() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [],
        [_row(feedback_id=55, vote="down")],
    ]
    sql.insert_responses = [ForgeExecResult(rowcount=1, lastrowid=55)]

    svc = PromptFeedbackService(sql=sql, max_payload_bytes=1024)
    out = svc.save_feedback(
        workspace_id="ws-1",
        user_id="user-1",
        trace_id="trace-55",
        vote="down",
        response_json={"answer": "bad"},
        feedback_comment="The domain was wrong",
        meta={"intent": "attendance"},
    )

    assert out.status == "analysis_pending"
    assert sql.insert_calls[0].params["meta_json"] == (
        '{"intent":"attendance","_feedback_learning":{"feedback_comment":"The domain was wrong"}}'
    )


def test_save_feedback_rejects_large_response_payload() -> None:
    sql = FakeForgeQueryPort()
    svc = PromptFeedbackService(sql=sql, max_payload_bytes=10)
    with pytest.raises(ForgeError, match="response_json exceeds max size"):
        svc.save_feedback(
            workspace_id="ws-1",
            user_id="user-1",
            vote="up",
            response_json={"text": "this is too large"},
        )


def test_list_feedback_returns_rows_without_payload_by_default() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": 1,
                "workspace_id": "ws-1",
                "user_id": "user-1",
                "trace_id": "t-1",
                "vote": "up",
                "normalized_prompt": "n",
                "prompt_text": "p",
                "response_json": {"a": 1},
                "meta_json": {"m": 1},
                "created_at": datetime(2026, 1, 1, 12, 0, 0),
                "updated_at": datetime(2026, 1, 1, 12, 1, 0),
            }
        ],
        [{"total": 1}],
    ]
    svc = PromptFeedbackService(sql=sql, max_payload_bytes=1024)

    out = svc.list_feedback(workspace_id="ws-1", limit=50, offset=0)
    assert out["count"] == 1
    assert out["total"] == 1
    assert "response_json" not in out["rows"][0]
    assert "meta_json" not in out["rows"][0]


def test_list_feedback_includes_payload_when_requested() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": 2,
                "workspace_id": "ws-1",
                "user_id": "user-1",
                "trace_id": "t-2",
                "vote": "down",
                "normalized_prompt": None,
                "prompt_text": None,
                "response_json": '{"x":2}',
                "meta_json": '{"model":"gpt"}',
                "created_at": datetime(2026, 1, 1, 12, 0, 0),
                "updated_at": datetime(2026, 1, 1, 12, 1, 0),
            }
        ],
        [{"total": 1}],
    ]
    svc = PromptFeedbackService(sql=sql, max_payload_bytes=1024)

    out = svc.list_feedback(workspace_id="ws-1", include_payload=True)
    assert out["rows"][0]["response_json"] == {"x": 2}
    assert out["rows"][0]["meta_json"] == {"model": "gpt"}


def test_delete_feedback_deletes_record() -> None:
    sql = FakeForgeQueryPort()
    sql.write_responses = [1]
    svc = PromptFeedbackService(sql=sql, max_payload_bytes=1024)

    out = svc.delete_feedback(workspace_id="ws-1", feedback_id=9)
    assert out.deleted is True
    assert out.id == 9


def test_delete_feedback_raises_not_found() -> None:
    sql = FakeForgeQueryPort()
    sql.write_responses = [0]
    svc = PromptFeedbackService(sql=sql, max_payload_bytes=1024)

    with pytest.raises(ForgeError) as exc:
        svc.delete_feedback(workspace_id="ws-1", feedback_id=9)
    assert exc.value.status_code == 404


def test_delete_feedback_rejects_non_integer_feedback_id() -> None:
    svc = PromptFeedbackService(sql=FakeForgeQueryPort(), max_payload_bytes=1024)

    with pytest.raises(ForgeError, match="feedback_id must be an integer"):
        svc.delete_feedback(workspace_id="ws-1", feedback_id="bad")


def test_delete_feedback_surfaces_unexpected_integer_conversion_errors() -> None:
    class _BrokenFeedbackId:
        def __int__(self) -> int:
            raise AssertionError("unexpected feedback id conversion failure")

    svc = PromptFeedbackService(sql=FakeForgeQueryPort(), max_payload_bytes=1024)

    with pytest.raises(AssertionError, match="unexpected feedback id conversion failure"):
        svc.delete_feedback(workspace_id="ws-1", feedback_id=_BrokenFeedbackId())
