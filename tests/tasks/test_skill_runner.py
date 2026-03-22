from __future__ import annotations

from datetime import datetime, timezone

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
    monkeypatch.setattr("app.services.query_forge_service.QueryForgeService", _FakeQueryForgeService)
    monkeypatch.setattr("app.services.domain_resolver.DomainResolver", lambda workspace_id: {"workspace_id": workspace_id})

    bundle = skill_runner._execute_skill_query(workspace_id="ws-1", query_id="query-7")

    assert bundle["rows"] == [{"amount": 99.5, "status": "ready"}]
    assert bundle["column_names"] == ["amount", "status"]
    assert bundle["column_types"] == {"amount": "number", "status": "string"}
    assert bundle["row_count"] == 1
    assert bundle["query_name"] == "Revenue Snapshot"
    assert bundle["execution_time_ms"] >= 0
    assert isinstance(bundle["executed_at"], datetime)


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
