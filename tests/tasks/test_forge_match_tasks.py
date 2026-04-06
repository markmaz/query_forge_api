from __future__ import annotations

import pytest

import app.tasks.forge_match_tasks as forge_match_tasks


def test_analyze_forge_match_session_task_logs_expected_runtime_failures(monkeypatch) -> None:
    class _Service:
        def __init__(self, *, sql):
            self.sql = sql

        def run_analyze_job(self, **kwargs):
            del kwargs
            raise RuntimeError("expected analyze failure")

    logger_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(forge_match_tasks, "ForgeMetaSQL", lambda: object())
    monkeypatch.setattr(forge_match_tasks, "ForgeMatchMappingService", _Service)
    monkeypatch.setattr(
        forge_match_tasks.logger,
        "exception",
        lambda message, job_id, session_id: logger_calls.append((job_id, session_id)),
    )

    with pytest.raises(RuntimeError, match="expected analyze failure"):
        forge_match_tasks.analyze_forge_match_session_task.run(
            job_id="job-1",
            workspace_id="ws-1",
            session_id="session-1",
        )

    assert logger_calls == [("job-1", "session-1")]


def test_analyze_forge_match_session_task_surfaces_unexpected_failures(monkeypatch) -> None:
    class _Service:
        def __init__(self, *, sql):
            self.sql = sql

        def run_analyze_job(self, **kwargs):
            del kwargs
            raise AssertionError("unexpected analyze bug")

    logger_calls: list[tuple[str, str]] = []

    monkeypatch.setattr(forge_match_tasks, "ForgeMetaSQL", lambda: object())
    monkeypatch.setattr(forge_match_tasks, "ForgeMatchMappingService", _Service)
    monkeypatch.setattr(
        forge_match_tasks.logger,
        "exception",
        lambda message, job_id, session_id: logger_calls.append((job_id, session_id)),
    )

    with pytest.raises(AssertionError, match="unexpected analyze bug"):
        forge_match_tasks.analyze_forge_match_session_task.run(
            job_id="job-1",
            workspace_id="ws-1",
            session_id="session-1",
        )

    assert logger_calls == []
