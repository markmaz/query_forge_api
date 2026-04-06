from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.services.forge_match.session_job_coordinator import ForgeMatchSessionJobCoordinator
from tests._support.fakes import FakeForgeQueryPort


def _build_coordinator(*, sql: FakeForgeQueryPort | None = None) -> ForgeMatchSessionJobCoordinator:
    return ForgeMatchSessionJobCoordinator(
        sql=sql or FakeForgeQueryPort(),
        session_reader=SimpleNamespace(
            get_session_row=lambda **_kwargs: {},
            load_source_rows=lambda **_kwargs: [],
            load_mapping_rows=lambda **_kwargs: [],
            build_summary=lambda **_kwargs: {},
        ),
        pipeline_executor=SimpleNamespace(execute=lambda definition, context: context),
        run_row_pipeline=lambda **_kwargs: None,
        existing_results_by_source=lambda **_kwargs: {},
        clear_results=lambda **_kwargs: None,
        persist_failure_result=lambda **_kwargs: None,
        persist_session_analysis_trace=lambda **_kwargs: {},
    )


def test_is_cancel_requested_returns_false_on_sqlalchemy_error() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_exceptions = [SQLAlchemyError("read failed")]
    coordinator = _build_coordinator(sql=sql)

    assert coordinator.is_cancel_requested(session_id="sess-1") is False


def test_is_cancel_requested_surfaces_unexpected_errors() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_exceptions = [RuntimeError("query wiring bug")]
    coordinator = _build_coordinator(sql=sql)

    with pytest.raises(RuntimeError, match="query wiring bug"):
        coordinator.is_cancel_requested(session_id="sess-1")


def test_update_session_progress_falls_back_when_extended_columns_missing() -> None:
    sql = FakeForgeQueryPort()
    sql.write_exceptions = [SQLAlchemyError("Unknown column 'analyzed_count'")]
    coordinator = _build_coordinator(sql=sql)

    coordinator.update_session_progress(
        session_id="sess-1",
        status="queued",
        job_id="job-1",
        source_total=10,
        source_done=1,
        source_skipped=0,
        source_failed=0,
        current_phase="queued",
        current_source_row_id=None,
    )

    assert coordinator._extended_progress_columns_supported is False
    assert len(sql.write_calls) == 2
    assert "analyzed_count = :source_done" in sql.write_calls[0].query
    assert "analyzed_count = :source_done" not in sql.write_calls[1].query


def test_update_session_progress_surfaces_unexpected_write_errors() -> None:
    sql = FakeForgeQueryPort()
    sql.write_exceptions = [RuntimeError("write bug")]
    coordinator = _build_coordinator(sql=sql)

    with pytest.raises(RuntimeError, match="write bug"):
        coordinator.update_session_progress(
            session_id="sess-1",
            status="queued",
            job_id="job-1",
            source_total=10,
            source_done=1,
            source_skipped=0,
            source_failed=0,
            current_phase="queued",
            current_source_row_id=None,
        )

    assert coordinator._extended_progress_columns_supported is True


def test_run_analyze_job_marks_failed_progress_on_expected_runtime_error(monkeypatch) -> None:
    coordinator = _build_coordinator()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        coordinator,
        "_run_session_pipeline",
        lambda context: (_ for _ in ()).throw(RuntimeError("pipeline unavailable")),
    )
    monkeypatch.setattr(
        coordinator,
        "update_session_progress",
        lambda **kwargs: captured.update(kwargs),
    )

    with pytest.raises(RuntimeError, match="pipeline unavailable"):
        coordinator.run_analyze_job(
            workspace_id="ws-1",
            session_id="sess-1",
            top_n=8,
        )

    assert captured["session_id"] == "sess-1"
    assert captured["status"] == "failed"
    assert captured["current_phase"] == "failed"
    assert captured["analysis_error"] == "pipeline unavailable"


def test_run_analyze_job_surfaces_unexpected_pipeline_failures(monkeypatch) -> None:
    coordinator = _build_coordinator()
    update_called = False

    def _mark_update(**kwargs):
        nonlocal update_called
        del kwargs
        update_called = True

    monkeypatch.setattr(
        coordinator,
        "_run_session_pipeline",
        lambda context: (_ for _ in ()).throw(AssertionError("pipeline bug")),
    )
    monkeypatch.setattr(coordinator, "update_session_progress", _mark_update)

    with pytest.raises(AssertionError, match="pipeline bug"):
        coordinator.run_analyze_job(
            workspace_id="ws-1",
            session_id="sess-1",
            top_n=8,
        )

    assert update_called is False
