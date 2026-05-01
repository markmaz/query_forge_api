from __future__ import annotations

from app.adapters.query_port import ForgeExecResult
from app.repositories.feedback_learning import PromptFailureAnalysisRepository
from tests._support.fakes import FakeForgeQueryPort


def test_create_pending_returns_inserted_id() -> None:
    sql = FakeForgeQueryPort()
    sql.insert_responses.append(ForgeExecResult(rowcount=1, lastrowid=77))

    repo = PromptFailureAnalysisRepository(sql=sql)
    created_id = repo.create_pending(
        prompt_feedback_id=15,
        evaluator_model="gpt-4.1-mini",
        evaluator_version="2026-04-23",
    )

    assert created_id == 77
    assert sql.insert_calls[0].params == {
        "prompt_feedback_id": 15,
        "evaluator_model": "gpt-4.1-mini",
        "evaluator_version": "2026-04-23",
    }


def test_mark_completed_serializes_analysis_json() -> None:
    sql = FakeForgeQueryPort()
    sql.write_responses.append(1)

    repo = PromptFailureAnalysisRepository(sql=sql)
    updated = repo.mark_completed(
        analysis_id=19,
        failure_verdict="semantic_gap",
        confidence=0.91,
        analysis_json={"reason": "missing alias"},
        raw_llm_output="model output",
    )

    assert updated == 1
    assert sql.write_calls[0].params == {
        "id": 19,
        "failure_verdict": "semantic_gap",
        "confidence": 0.91,
        "analysis_json": '{"reason":"missing alias"}',
        "raw_llm_output": "model output",
    }


def test_get_by_feedback_id_parses_analysis_json() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses.append(
        [
            {
                "id": 88,
                "prompt_feedback_id": 15,
                "evaluator_model": "gpt-4.1-mini",
                "evaluator_version": "2026-04-23",
                "status": "completed",
                "failure_verdict": "semantic_gap",
                "confidence": 0.91,
                "analysis_json": '{"reason":"missing alias"}',
                "raw_llm_output": "raw",
                "error_message": None,
                "created_at": "2026-04-23 10:00:00",
                "updated_at": "2026-04-23 10:01:00",
            }
        ]
    )

    repo = PromptFailureAnalysisRepository(sql=sql)
    row = repo.get_by_feedback_id(prompt_feedback_id=15)

    assert row is not None
    assert row["analysis_json"] == {"reason": "missing alias"}

