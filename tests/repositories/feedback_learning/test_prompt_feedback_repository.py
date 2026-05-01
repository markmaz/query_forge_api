from __future__ import annotations

from app.repositories.feedback_learning import PromptFeedbackRepository
from tests._support.fakes import FakeForgeQueryPort


def test_get_feedback_parses_json_payloads() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses.append(
        [
            {
                "id": 41,
                "workspace_id": "ws-1",
                "user_id": "user-1",
                "trace_id": "trace-1",
                "vote": "down",
                "normalized_prompt": "show attendance",
                "prompt_text": "Show attendance",
                "response_json": '{"intent":"attendance"}',
                "meta_json": '{"domain_id":6}',
                "created_at": "2026-04-23 10:00:00",
                "updated_at": "2026-04-23 10:01:00",
            }
        ]
    )

    repo = PromptFeedbackRepository(sql=sql)
    row = repo.get_feedback(prompt_feedback_id=41)

    assert row is not None
    assert row["response_json"] == {"intent": "attendance"}
    assert row["meta_json"] == {"domain_id": 6}
    assert sql.query_mappings_calls[0].params == {"id": 41}


def test_list_negative_feedback_without_analysis_applies_optional_filters() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses.append(
        [
            {
                "id": 51,
                "workspace_id": "ws-9",
                "user_id": "user-9",
                "trace_id": "trace-9",
                "vote": "down",
                "normalized_prompt": "days off",
                "prompt_text": "Show days off",
                "response_json": '{"result":"planner"}',
                "meta_json": None,
                "created_at": "2026-04-20 09:00:00",
                "updated_at": "2026-04-20 09:01:00",
            }
        ]
    )

    repo = PromptFeedbackRepository(sql=sql)
    rows = repo.list_negative_feedback_without_analysis(
        limit=25,
        workspace_id="ws-9",
        date_from="2026-04-01",
        date_to="2026-04-22",
    )

    assert len(rows) == 1
    assert rows[0]["response_json"] == {"result": "planner"}
    params = sql.query_mappings_calls[0].params
    assert params == {
        "workspace_id": "ws-9",
        "date_from": "2026-04-01",
        "date_to": "2026-04-22",
        "limit": 25,
    }

