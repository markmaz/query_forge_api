from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.tasks import skill_runner


class _FakeForgeMetaSQL:
    def __init__(self, rows=None):
        self._rows = rows or {}
        self.write_calls = []

    def execute_query_mappings(self, query, params=None):
        sql = " ".join(str(query).split()).lower()
        if "from skill_schedules ss" in sql and "join query_skills qs" in sql:
            return list(self._rows.get("due_schedules") or [])
        if "from query_skills" in sql:
            return list(self._rows.get("query_skills") or [])
        if "from saved_query" in sql:
            return list(self._rows.get("saved_query") or [])
        return []

    def execute_write(self, query, params=None):
        self.write_calls.append((query, params or {}))
        return 1


def test_run_execute_builds_full_skill_context(app, monkeypatch):
    fixed_now = datetime(2026, 3, 19, 18, 0, tzinfo=timezone.utc)
    sql = _FakeForgeMetaSQL(
        rows={
            "query_skills": [
                {
                    "id": "skill-1",
                    "workspace_id": "ws-1",
                    "name": "Weekly digest",
                    "skill_type": "ai_summary_digest",
                    "query_id": "query-7",
                    "config_json": {
                        "recipients": ["team@example.com"],
                        "subject": "Weekly Digest",
                        "_qf_skill": {
                            "description": "Should not leak into runtime config",
                            "status": "active",
                        },
                    },
                    "is_active": 1,
                }
            ]
        }
    )
    captured = {}

    class _FakeSkill:
        def execute(self, context):
            captured["context"] = context
            return {"success": True, "message": "ok"}

    monkeypatch.setattr("app.adapters.mysql_sql_executor.ForgeMetaSQL", lambda: sql)
    monkeypatch.setattr(
        skill_runner,
        "_execute_skill_query",
        lambda **kwargs: {
            "rows": [{"amount": 42.5, "status": "open"}],
            "columns": [
                {"name": "amount", "type": "number"},
                {"name": "status", "dataType": "string"},
            ],
            "column_names": ["amount", "status"],
            "column_types": {"amount": "number", "status": "string"},
            "row_count": 1,
            "query_name": "Open Orders",
            "execution_time_ms": 37,
            "executed_at": fixed_now,
        },
    )
    monkeypatch.setattr(skill_runner, "_get_workspace_config", lambda workspace_id: {"llm": {"provider": "openai"}})
    monkeypatch.setattr("app.skills.registry.SkillRegistry.get", lambda skill_type: _FakeSkill)

    app.config["FRONTEND_BASE_URL"] = "https://app.queryforge.local"
    with app.app_context():
        result = skill_runner._run_execute(
            skill_id="skill-1",
            workspace_id="ws-1",
            execution_id="exec-1",
            triggered_by="schedule",
        )

    context = captured["context"]
    assert result == {"success": True, "message": "ok"}
    assert context.workspace_id == "ws-1"
    assert context.skill_id == "skill-1"
    assert context.execution_id == "exec-1"
    assert context.query_id == "query-7"
    assert context.triggered_by == "schedule"
    assert context.config == {
        "recipients": ["team@example.com"],
        "subject": "Weekly Digest",
    }
    assert context.rows == [{"amount": 42.5, "status": "open"}]
    assert context.results == [{"amount": 42.5, "status": "open"}]
    assert context.columns == ["amount", "status"]
    assert context.metadata.query_id == "query-7"
    assert context.metadata.query_name == "Open Orders"
    assert context.metadata.column_names == ["amount", "status"]
    assert context.metadata.column_types == {"amount": "number", "status": "string"}
    assert context.metadata.row_count == 1
    assert context.metadata.execution_time_ms == 37
    assert context.metadata.executed_at == fixed_now
    assert context.workspace_config == {"llm": {"provider": "openai"}}
    assert context.frontend_base_url == "https://app.queryforge.local"


def test_run_execute_marks_failed_on_expected_runtime_error(app, monkeypatch):
    sql = _FakeForgeMetaSQL(
        rows={
            "query_skills": [
                {
                    "id": "skill-1",
                    "workspace_id": "ws-1",
                    "name": "Weekly digest",
                    "skill_type": "ai_summary_digest",
                    "query_id": None,
                    "config_json": {},
                    "is_active": 1,
                }
            ]
        }
    )

    class _FailingSkill:
        def execute(self, context):
            del context
            raise RuntimeError("expected runtime failure")

    monkeypatch.setattr("app.adapters.mysql_sql_executor.ForgeMetaSQL", lambda: sql)
    monkeypatch.setattr(skill_runner, "_get_workspace_config", lambda workspace_id: {})
    monkeypatch.setattr("app.skills.registry.SkillRegistry.get", lambda skill_type: _FailingSkill)

    with app.app_context():
        with pytest.raises(RuntimeError, match="expected runtime failure"):
            skill_runner._run_execute(
                skill_id="skill-1",
                workspace_id="ws-1",
                execution_id="exec-1",
                triggered_by="schedule",
            )

    failed_update = next(
        (
            params
            for query, params in sql.write_calls
            if "UPDATE skill_executions SET status = 'failed'" in query
        ),
        None,
    )
    assert failed_update is not None
    assert failed_update["id"] == "exec-1"
    assert "expected runtime failure" in failed_update["err"]


def test_run_execute_surfaces_unexpected_errors(app, monkeypatch):
    sql = _FakeForgeMetaSQL(
        rows={
            "query_skills": [
                {
                    "id": "skill-1",
                    "workspace_id": "ws-1",
                    "name": "Weekly digest",
                    "skill_type": "ai_summary_digest",
                    "query_id": None,
                    "config_json": {},
                    "is_active": 1,
                }
            ]
        }
    )

    class _BuggySkill:
        def execute(self, context):
            del context
            raise AssertionError("unexpected skill bug")

    monkeypatch.setattr("app.adapters.mysql_sql_executor.ForgeMetaSQL", lambda: sql)
    monkeypatch.setattr(skill_runner, "_get_workspace_config", lambda workspace_id: {})
    monkeypatch.setattr("app.skills.registry.SkillRegistry.get", lambda skill_type: _BuggySkill)

    with app.app_context():
        with pytest.raises(AssertionError, match="unexpected skill bug"):
            skill_runner._run_execute(
                skill_id="skill-1",
                workspace_id="ws-1",
                execution_id="exec-1",
                triggered_by="schedule",
            )

    assert not any("UPDATE skill_executions SET status = 'failed'" in query for query, _ in sql.write_calls)


def test_execute_skill_query_returns_query_metadata_bundle(monkeypatch):
    sql = _FakeForgeMetaSQL(
        rows={
            "saved_query": [
                {
                    "sql_json": {"columns": [{"field": {"columnName": "amount"}}]},
                    "name": "Revenue Snapshot",
                }
            ]
        }
    )

    class _FakeWorkspaceContext:
        sql_exec = object()

    class _FakeWorkspaceBuilder:
        def build(self, workspace_id):
            assert workspace_id == "ws-1"
            return _FakeWorkspaceContext()

    class _FakeQueryForgeService:
        def __init__(self, executor, domain_resolver):
            self.executor = executor
            self.domain_resolver = domain_resolver

        def run(self, raw_query, mode, limit, offset):
            assert raw_query == {"columns": [{"field": {"columnName": "amount"}}]}
            assert mode == "export"
            assert limit == skill_runner._SKILL_EXECUTE_ROW_CAP
            assert offset == 0
            return type(
                "Result",
                (),
                {
                    "rows": [{"amount": 99.5, "status": "ready"}],
                    "columns": [
                        {"name": "amount", "type": "number"},
                        {"name": "status", "dataType": "string"},
                    ],
                },
            )()

    monkeypatch.setattr("app.adapters.mysql_sql_executor.ForgeMetaSQL", lambda: sql)
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.WorkspaceSqlContextBuilder",
        _FakeWorkspaceBuilder,
    )
    monkeypatch.setattr("app.services.query_forge.service.QueryForgeService", _FakeQueryForgeService)
    monkeypatch.setattr("app.services.domain_resolver.DomainResolver", lambda workspace_id: {"workspace_id": workspace_id})

    bundle = skill_runner._execute_skill_query(workspace_id="ws-1", query_id="query-7")

    assert bundle["rows"] == [{"amount": 99.5, "status": "ready"}]
    assert bundle["column_names"] == ["amount", "status"]
    assert bundle["column_types"] == {"amount": "number", "status": "string"}
    assert bundle["row_count"] == 1
    assert bundle["query_name"] == "Revenue Snapshot"
    assert bundle["execution_time_ms"] >= 0
    assert isinstance(bundle["executed_at"], datetime)


def test_execute_skill_query_accepts_saved_query_title_alias(monkeypatch):
    sql = _FakeForgeMetaSQL(
        rows={
            "saved_query": [
                {
                    "sql_json": {"columns": [{"field": {"columnName": "amount"}}]},
                    "name": "Title Aliased Query",
                }
            ]
        }
    )

    class _FakeWorkspaceContext:
        sql_exec = object()

    class _FakeWorkspaceBuilder:
        def build(self, workspace_id):
            return _FakeWorkspaceContext()

    class _FakeQueryForgeService:
        def __init__(self, executor, domain_resolver):
            self.executor = executor
            self.domain_resolver = domain_resolver

        def run(self, raw_query, mode, limit, offset):
            return type(
                "Result",
                (),
                {
                    "rows": [],
                    "columns": [],
                },
            )()

    monkeypatch.setattr("app.adapters.mysql_sql_executor.ForgeMetaSQL", lambda: sql)
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.WorkspaceSqlContextBuilder",
        _FakeWorkspaceBuilder,
    )
    monkeypatch.setattr("app.services.query_forge.service.QueryForgeService", _FakeQueryForgeService)
    monkeypatch.setattr("app.services.domain_resolver.DomainResolver", lambda workspace_id: {"workspace_id": workspace_id})

    bundle = skill_runner._execute_skill_query(workspace_id="ws-1", query_id="query-8")

    assert bundle["query_name"] == "Title Aliased Query"


def test_execute_skill_query_allows_global_saved_queries(monkeypatch):
    sql_seen = {}

    class _FakeForgeMetaSQL:
        def execute_query_mappings(self, query, params=None):
            sql_seen["query"] = " ".join(str(query).split())
            return [
                {
                    "sql_json": {"columns": [{"field": {"columnName": "amount"}}]},
                    "name": "Library Query",
                }
            ]

    class _FakeWorkspaceContext:
        sql_exec = object()

    class _FakeWorkspaceBuilder:
        def build(self, workspace_id):
            return _FakeWorkspaceContext()

    class _FakeQueryForgeService:
        def __init__(self, executor, domain_resolver):
            self.executor = executor
            self.domain_resolver = domain_resolver

        def run(self, raw_query, mode, limit, offset):
            return type("Result", (), {"rows": [], "columns": []})()

    monkeypatch.setattr("app.adapters.mysql_sql_executor.ForgeMetaSQL", _FakeForgeMetaSQL)
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.WorkspaceSqlContextBuilder",
        _FakeWorkspaceBuilder,
    )
    monkeypatch.setattr("app.services.query_forge.service.QueryForgeService", _FakeQueryForgeService)
    monkeypatch.setattr("app.services.domain_resolver.DomainResolver", lambda workspace_id: {"workspace_id": workspace_id})

    bundle = skill_runner._execute_skill_query(workspace_id="ws-1", query_id="query-9")

    assert bundle["query_name"] == "Library Query"
    assert "workspace_id = :ws OR workspace_id IS NULL" in sql_seen["query"]


def test_dispatch_due_advances_next_run_at_after_dispatch(app, monkeypatch):
    due_now = datetime(2026, 3, 21, 14, 0, 0)
    next_run = "2026-03-21T15:00:00+00:00"
    sql = _FakeForgeMetaSQL(
        rows={
            "due_schedules": [
                {
                    "schedule_id": "sched-1",
                    "skill_id": "skill-1",
                    "workspace_id": "ws-1",
                    "cron_expr": "0 * * * *",
                    "timezone": "UTC",
                    "next_run_at": due_now,
                    "catch_up": 0,
                }
            ]
        }
    )
    applied = {}

    class _FakeTask:
        def apply_async(self, *, kwargs):
            applied["kwargs"] = kwargs

    monkeypatch.setattr("app.adapters.mysql_sql_executor.ForgeMetaSQL", lambda: sql)
    monkeypatch.setattr("app.tasks.skill_runner.execute_skill", _FakeTask())
    monkeypatch.setattr("app.skills.schedule_utils.record_dispatch_heartbeat", lambda: None)
    monkeypatch.setattr("app.skills.schedule_utils.next_n_runs", lambda *args, **kwargs: [next_run])
    monkeypatch.setattr(skill_runner, "_is_overdue_by_more_than_one_interval", lambda *args, **kwargs: False)

    with app.app_context():
        result = skill_runner._run_dispatch_due()

    assert result["dispatched"] == 1
    assert applied["kwargs"]["skill_id"] == "skill-1"
    update_call = next(
        (params for query, params in sql.write_calls if "UPDATE skill_schedules SET last_run_at = :now, next_run_at = :next_run_at" in query),
        None,
    )
    assert update_call is not None
    assert update_call["next_run_at"] == datetime(2026, 3, 21, 15, 0, 0)


def test_dispatch_due_skips_expected_dispatch_runtime_failures(app, monkeypatch):
    due_now = datetime(2026, 3, 21, 14, 0, 0)
    sql = _FakeForgeMetaSQL(
        rows={
            "due_schedules": [
                {
                    "schedule_id": "sched-1",
                    "skill_id": "skill-1",
                    "workspace_id": "ws-1",
                    "cron_expr": "0 * * * *",
                    "timezone": "UTC",
                    "next_run_at": due_now,
                    "catch_up": 0,
                }
            ]
        }
    )

    class _FailingTask:
        def apply_async(self, *, kwargs):
            del kwargs
            raise RuntimeError("queue unavailable")

    monkeypatch.setattr("app.adapters.mysql_sql_executor.ForgeMetaSQL", lambda: sql)
    monkeypatch.setattr("app.tasks.skill_runner.execute_skill", _FailingTask())
    monkeypatch.setattr("app.skills.schedule_utils.record_dispatch_heartbeat", lambda: None)
    monkeypatch.setattr("app.skills.schedule_utils.next_n_runs", lambda *args, **kwargs: ["2026-03-21T15:00:00+00:00"])
    monkeypatch.setattr(skill_runner, "_is_overdue_by_more_than_one_interval", lambda *args, **kwargs: False)

    with app.app_context():
        result = skill_runner._run_dispatch_due()

    assert result["dispatched"] == 0
    assert result["items"] == []


def test_dispatch_due_surfaces_unexpected_dispatch_errors(app, monkeypatch):
    due_now = datetime(2026, 3, 21, 14, 0, 0)
    sql = _FakeForgeMetaSQL(
        rows={
            "due_schedules": [
                {
                    "schedule_id": "sched-1",
                    "skill_id": "skill-1",
                    "workspace_id": "ws-1",
                    "cron_expr": "0 * * * *",
                    "timezone": "UTC",
                    "next_run_at": due_now,
                    "catch_up": 0,
                }
            ]
        }
    )

    class _BuggyTask:
        def apply_async(self, *, kwargs):
            del kwargs
            raise AssertionError("unexpected queue bug")

    monkeypatch.setattr("app.adapters.mysql_sql_executor.ForgeMetaSQL", lambda: sql)
    monkeypatch.setattr("app.tasks.skill_runner.execute_skill", _BuggyTask())
    monkeypatch.setattr("app.skills.schedule_utils.record_dispatch_heartbeat", lambda: None)
    monkeypatch.setattr("app.skills.schedule_utils.next_n_runs", lambda *args, **kwargs: ["2026-03-21T15:00:00+00:00"])
    monkeypatch.setattr(skill_runner, "_is_overdue_by_more_than_one_interval", lambda *args, **kwargs: False)

    with app.app_context():
        with pytest.raises(AssertionError, match="unexpected queue bug"):
            skill_runner._run_dispatch_due()


def test_get_workspace_config_returns_empty_on_expected_runtime_failure(monkeypatch):
    class _WorkspaceLLMService:
        def get_llm_for_role(self, workspace_id, role):
            del workspace_id, role
            raise RuntimeError("llm config unavailable")

    monkeypatch.setattr(
        "app.services.tenancy.workspace_llm_service.WorkspaceLLMService",
        _WorkspaceLLMService,
    )

    assert skill_runner._get_workspace_config("ws-1") == {}


def test_get_workspace_config_surfaces_unexpected_failures(monkeypatch):
    class _WorkspaceLLMService:
        def get_llm_for_role(self, workspace_id, role):
            del workspace_id, role
            raise AssertionError("workspace config bug")

    monkeypatch.setattr(
        "app.services.tenancy.workspace_llm_service.WorkspaceLLMService",
        _WorkspaceLLMService,
    )

    with pytest.raises(AssertionError, match="workspace config bug"):
        skill_runner._get_workspace_config("ws-1")
