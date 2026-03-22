from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict

import app.decorators.ownership as ownership
import app.decorators.security as security
import app.services.ownership_service as ownership_service
import app.services.rbac_service as rbac_service


def _headers(monkeypatch, *, actor_id: str = "user-1", roles: set[str] | None = None) -> Dict[str, str]:
    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": actor_id, "username": actor_id, "is_admin": True},
    )
    monkeypatch.setattr(
        security.workspace_access_service,
        "assert_workspace_access",
        lambda *, user_id, workspace_id: workspace_id,
    )
    monkeypatch.setattr(
        rbac_service,
        "get_effective_roles",
        lambda user_id, workspace_id=None: set(roles or {"super_admin"}),
    )
    monkeypatch.setattr(
        ownership,
        "_load_model",
        lambda model_name, object_id, workspace_id=None: type(
            "_OwnedSkill",
            (),
            {"created_by": actor_id, "is_shared": False},
        )(),
    )
    monkeypatch.setattr(ownership_service, "_has_admin_access", lambda *args, **kwargs: False)
    return {"Authorization": "Bearer token-1", "X-Workspace-Id": "ws-1"}


class _FakeSkillsSQL:
    list_rows: list[dict[str, Any]] = []
    detail_row: dict[str, Any] | None = None
    execution_rows: list[dict[str, Any]] = []
    schedule_rows: list[dict[str, Any]] = []
    total_rows: list[dict[str, Any]] = [{"cnt": 1}]
    write_calls: list[tuple[str, dict[str, Any]]] = []
    current_row: dict[str, Any] | None = None

    def __init__(self) -> None:
        pass

    def execute_query_mappings(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        normalized = " ".join(query.split())
        params = params or {}
        if "FROM query_skills qs LEFT JOIN skill_executions se" in normalized and "WHERE qs.workspace_id = :ws" in normalized:
            return [dict(row) for row in type(self).list_rows]
        if normalized.startswith("SELECT COUNT(*) AS cnt FROM skill_executions"):
            return [dict(row) for row in type(self).total_rows]
        if normalized.startswith("SELECT COUNT(*) AS cnt FROM skill_schedules"):
            return [{"cnt": len(type(self).schedule_rows)}]
        if "FROM skill_schedules" in normalized and "WHERE skill_id = :skill_id AND workspace_id = :ws" in normalized:
            rows = [dict(row) for row in type(self).schedule_rows if row.get("skill_id") == params.get("skill_id") and row.get("workspace_id") == params.get("ws")]
            if "ORDER BY created_at DESC LIMIT 1" in normalized:
                return rows[:1]
            return rows
        if "FROM skill_schedules" in normalized and "WHERE id = :id" in normalized:
            rows = [dict(row) for row in type(self).schedule_rows if row.get("id") == params.get("id")]
            return rows[:1]
        if "FROM skill_schedules" in normalized and "WHERE workspace_id = :ws" in normalized:
            return [dict(row) for row in type(self).schedule_rows if row.get("workspace_id") == params.get("ws")]
        if "FROM skill_executions" in normalized:
            return [dict(row) for row in type(self).execution_rows]
        if "SELECT id, skill_type, config_json, is_active FROM query_skills" in normalized:
            row = type(self).current_row
            return [dict(row)] if row else []
        if "FROM query_skills qs WHERE qs.id = :id" in normalized:
            row = type(self).current_row or type(self).detail_row
            return [dict(row)] if row else []
        if "FROM query_skills qs LEFT JOIN skill_executions se" in normalized and "WHERE qs.id = :id" in normalized:
            row = type(self).current_row or type(self).detail_row
            return [dict(row)] if row else []
        if normalized.startswith("SELECT id FROM query_skills WHERE id = :id AND workspace_id = :ws LIMIT 1"):
            row = type(self).current_row
            return [{"id": row["id"]}] if row else []
        return []

    def execute_write(self, query: str, params: dict[str, Any] | None = None) -> int:
        params = dict(params or {})
        type(self).write_calls.append((query, params))
        normalized = " ".join(query.split())
        if normalized.startswith("INSERT INTO query_skills"):
            type(self).current_row = {
                "id": params["id"],
                "workspace_id": params["ws"],
                "name": params["name"],
                "skill_type": params["skill_type"],
                "query_id": params["query_id"],
                "config_json": params["config_json"],
                "is_active": params["is_active"],
                "created_by": params["created_by"],
                "created_at": params["now"],
                "updated_at": None,
                "last_run_at": None,
                "run_count": 0,
            }
        if normalized.startswith("INSERT INTO skill_schedules"):
            type(self).schedule_rows = [
                {
                    "id": params["id"],
                    "skill_id": params["skill_id"],
                    "workspace_id": params["workspace_id"],
                    "cron_expr": params["cron_expr"],
                    "timezone": params["timezone"],
                    "next_run_at": params["next_run_at"],
                    "last_run_at": None,
                    "is_active": params["is_active"],
                    "catch_up": 0,
                    "created_at": datetime(2026, 3, 19, 12, 0, 0),
                    "updated_at": None,
                }
            ]
        if normalized.startswith("UPDATE skill_schedules SET"):
            next_rows = []
            for row in type(self).schedule_rows:
                if (
                    row.get("id") == params.get("id")
                    or (
                        row.get("skill_id") == params.get("skill_id")
                        and row.get("workspace_id") == params.get("ws")
                    )
                ):
                    updated = dict(row)
                    updated.update({k: v for k, v in params.items() if k not in {"id", "updated_at", "skill_id", "ws", "now"}})
                    if "now" in params:
                        updated["updated_at"] = params["now"]
                    elif "updated_at" in params:
                        updated["updated_at"] = params["updated_at"]
                    next_rows.append(updated)
                else:
                    next_rows.append(dict(row))
            type(self).schedule_rows = next_rows
        if normalized.startswith("UPDATE query_skills SET"):
            current = dict(type(self).current_row or {})
            current.update({k: v for k, v in params.items() if k not in {"id", "updated_at"}})
            type(self).current_row = current
        return 1


def _install_fake_sql(monkeypatch) -> None:
    import app.adapters.mysql_sql_executor as mysql_sql_executor

    monkeypatch.setattr(mysql_sql_executor, "ForgeMetaSQL", _FakeSkillsSQL)


def test_skills_list_returns_normalized_workflow_fields(client, monkeypatch):
    _install_fake_sql(monkeypatch)
    _FakeSkillsSQL.list_rows = [
        {
            "id": "skill-1",
            "workspace_id": "ws-1",
            "name": "Revenue Digest",
            "skill_type": "email_delivery",
            "query_id": "query-1",
            "config_json": json.dumps(
                {
                    "recipients": ["ops@example.com"],
                    "_qf_skill": {
                        "description": "Daily digest",
                        "status": "active",
                        "skill_type": "email_report",
                        "query_name": "Revenue Query",
                        "trigger": {"id": "t1", "kind": "trigger", "type": "schedule", "config": {}},
                        "conditions": [],
                        "actions": [{"id": "a1", "kind": "action", "type": "email_report", "config": {}}],
                    },
                }
            ),
            "is_active": 1,
            "created_by": "user-1",
            "created_at": datetime(2026, 3, 19, 10, 0, 0),
            "updated_at": datetime(2026, 3, 19, 11, 0, 0),
            "last_run_at": datetime(2026, 3, 19, 12, 0, 0),
            "run_count": 3,
        }
    ]

    resp = client.get(
        "/api/v1/skills?status=active&skill_type=email_report&q=revenue",
        headers=_headers(monkeypatch),
    )

    assert resp.status_code == 200
    row = resp.json["data"][0]
    assert row["skill_type"] == "email_report"
    assert row["status"] == "active"
    assert row["description"] == "Daily digest"
    assert row["query_name"] == "Revenue Query"
    assert row["trigger"]["type"] == "schedule"
    assert row["actions"][0]["type"] == "email_report"
    assert row["run_count"] == 3


def test_skills_patch_persists_workflow_meta_and_status(client, monkeypatch):
    _install_fake_sql(monkeypatch)
    _FakeSkillsSQL.write_calls = []
    _FakeSkillsSQL.schedule_rows = []
    _FakeSkillsSQL.current_row = {
        "id": "skill-2",
        "workspace_id": "ws-1",
        "name": "Existing Skill",
        "skill_type": "email_delivery",
        "query_id": "query-2",
        "config_json": json.dumps({"recipients": ["old@example.com"]}),
        "is_active": 1,
        "created_by": "user-1",
        "created_at": datetime(2026, 3, 19, 9, 0, 0),
        "updated_at": datetime(2026, 3, 19, 9, 30, 0),
        "last_run_at": None,
        "run_count": 0,
    }

    resp = client.patch(
        "/api/v1/skills/skill-2",
        headers=_headers(monkeypatch),
        json={
            "description": "Updated description",
            "status": "paused",
            "skill_type": "email_report",
            "trigger": {"id": "t1", "kind": "trigger", "type": "schedule", "config": {"time": "08:00"}},
            "conditions": [],
            "actions": [
                {
                    "id": "a1",
                    "kind": "action",
                    "type": "email_report",
                    "config": {"recipients": "ops@example.com, finance@example.com", "subject": "Morning report"},
                }
            ],
        },
    )

    assert resp.status_code == 200
    assert resp.json["data"]["status"] == "paused"
    assert resp.json["data"]["skill_type"] == "email_report"

    write_query, write_params = next(
        (query, params)
        for query, params in _FakeSkillsSQL.write_calls
        if "UPDATE query_skills SET" in " ".join(query.split())
    )
    persisted = json.loads(write_params["config_json"])
    assert persisted["recipients"] == ["ops@example.com", "finance@example.com"]
    assert persisted["_qf_skill"]["description"] == "Updated description"
    assert persisted["_qf_skill"]["status"] == "paused"
    assert write_params["is_active"] == 0


def test_skills_create_persists_destination_id_in_runtime_config(client, monkeypatch):
    _install_fake_sql(monkeypatch)
    _FakeSkillsSQL.write_calls = []
    _FakeSkillsSQL.schedule_rows = []
    _FakeSkillsSQL.current_row = None

    resp = client.post(
        "/api/v1/skills",
        headers=_headers(monkeypatch),
        json={
            "name": "Destination digest",
            "skill_type": "email_report",
            "query_id": "query-9",
            "description": "Morning digest",
            "status": "active",
            "trigger": {
                "id": "trigger-1",
                "kind": "trigger",
                "type": "schedule",
                "enabled": True,
                "config": {
                    "frequency": "daily",
                    "time": "08:15",
                    "timezone": "America/Chicago",
                    "active": True,
                },
            },
            "actions": [
                {
                    "id": "a1",
                    "kind": "action",
                    "type": "email_report",
                    "config": {
                        "destination_id": 23,
                        "subject": "Weekly",
                    },
                }
            ],
        },
    )

    assert resp.status_code == 201
    write_query, write_params = next(
        (query, params)
        for query, params in _FakeSkillsSQL.write_calls
        if "INSERT INTO query_skills" in " ".join(query.split())
    )
    persisted = json.loads(write_params["config_json"])
    assert persisted["destination_id"] == 23
    assert persisted["recipients"] == []
    assert persisted["_qf_skill"]["actions"][0]["config"]["destination_id"] == 23


def test_skills_create_persists_all_channels_for_mixed_delivery_actions(client, monkeypatch):
    _install_fake_sql(monkeypatch)
    _FakeSkillsSQL.write_calls = []
    _FakeSkillsSQL.schedule_rows = []
    _FakeSkillsSQL.current_row = None

    resp = client.post(
        "/api/v1/skills",
        headers=_headers(monkeypatch),
        json={
            "name": "Slack and email digest",
            "skill_type": "slack_delivery",
            "query_id": "query-9",
            "description": "Deliver to both channels",
            "status": "active",
            "trigger": {
                "id": "trigger-1",
                "kind": "trigger",
                "type": "schedule",
                "enabled": True,
                "config": {
                    "frequency": "daily",
                    "time": "08:15",
                    "timezone": "America/Chicago",
                    "active": True,
                },
            },
            "actions": [
                {
                    "id": "a1",
                    "kind": "action",
                    "type": "slack_delivery",
                    "config": {
                        "destination_id": 1,
                    },
                },
                {
                    "id": "a2",
                    "kind": "action",
                    "type": "email_report",
                    "config": {
                        "destination_id": 23,
                        "subject": "Weekly",
                    },
                },
            ],
        },
    )

    assert resp.status_code == 201
    _, write_params = next(
        (query, params)
        for query, params in _FakeSkillsSQL.write_calls
        if "INSERT INTO query_skills" in " ".join(query.split())
    )
    persisted = json.loads(write_params["config_json"])
    assert persisted["channels"] == [
        {"type": "slack", "destination_id": 1},
        {"type": "email", "destination_id": 23},
    ]


def test_skills_create_syncs_schedule_from_trigger(client, monkeypatch):
    _install_fake_sql(monkeypatch)
    _FakeSkillsSQL.write_calls = []
    _FakeSkillsSQL.schedule_rows = []
    _FakeSkillsSQL.current_row = None

    resp = client.post(
        "/api/v1/skills",
        headers=_headers(monkeypatch),
        json={
            "name": "Scheduled digest",
            "skill_type": "email_report",
            "query_id": "query-9",
            "description": "Morning digest",
            "status": "active",
            "trigger": {
                "id": "trigger-1",
                "kind": "trigger",
                "type": "schedule",
                "enabled": True,
                "config": {
                    "frequency": "weekly",
                    "day_of_week": "friday",
                    "time": "08:15",
                    "timezone": "America/Chicago",
                    "active": True,
                },
            },
            "actions": [
                {
                    "id": "a1",
                    "kind": "action",
                    "type": "email_report",
                    "config": {"recipients": ["ops@example.com"], "subject": "Weekly"},
                }
            ],
        },
    )

    assert resp.status_code == 201
    assert len(_FakeSkillsSQL.schedule_rows) == 1
    row = _FakeSkillsSQL.schedule_rows[0]
    assert row["cron_expr"] == "15 8 * * 5"
    assert row["timezone"] == "America/Chicago"
    assert row["is_active"] == 1
    assert row["next_run_at"] is not None


def test_skills_patch_deactivates_schedule_when_paused(client, monkeypatch):
    _install_fake_sql(monkeypatch)
    _FakeSkillsSQL.write_calls = []
    _FakeSkillsSQL.current_row = {
        "id": "skill-2",
        "workspace_id": "ws-1",
        "name": "Existing Skill",
        "skill_type": "email_delivery",
        "query_id": "query-2",
        "config_json": json.dumps(
            {
                "recipients": ["old@example.com"],
                "_qf_skill": {
                    "status": "active",
                    "trigger": {
                        "id": "t1",
                        "kind": "trigger",
                        "type": "schedule",
                        "config": {"frequency": "daily", "time": "08:00", "timezone": "UTC", "active": True},
                    },
                },
            }
        ),
        "is_active": 1,
        "created_by": "user-1",
        "created_at": datetime(2026, 3, 19, 9, 0, 0),
        "updated_at": datetime(2026, 3, 19, 9, 30, 0),
        "last_run_at": None,
        "run_count": 0,
    }
    _FakeSkillsSQL.schedule_rows = [
        {
            "id": "sched-1",
            "skill_id": "skill-2",
            "workspace_id": "ws-1",
            "cron_expr": "0 8 * * *",
            "timezone": "UTC",
            "next_run_at": datetime(2026, 3, 20, 8, 0, 0),
            "last_run_at": None,
            "is_active": 1,
            "catch_up": 0,
            "created_at": datetime(2026, 3, 19, 9, 0, 0),
            "updated_at": None,
        }
    ]

    resp = client.patch(
        "/api/v1/skills/skill-2",
        headers=_headers(monkeypatch),
        json={"status": "paused"},
    )

    assert resp.status_code == 200
    assert len(_FakeSkillsSQL.schedule_rows) == 1
    row = _FakeSkillsSQL.schedule_rows[0]
    assert row["is_active"] == 0
    assert row["next_run_at"] is None


def test_schedule_validate_accepts_trigger_payload(client, monkeypatch):
    resp = client.post(
        "/api/v1/skills/schedule/validate",
        headers=_headers(monkeypatch),
        json={
            "trigger": {
                "type": "schedule",
                "config": {
                    "frequency": "weekly",
                    "day_of_week": "friday",
                    "time": "08:15",
                    "timezone": "America/Chicago",
                },
            }
        },
    )

    assert resp.status_code == 200
    assert resp.json["valid"] is True
    assert resp.json["cron_expression"] == "15 8 * * 5"
    assert resp.json["timezone"] == "America/Chicago"
    assert len(resp.json["upcoming"]) == 5


def test_skills_runs_alias_returns_execution_rows(client, monkeypatch):
    _install_fake_sql(monkeypatch)
    _FakeSkillsSQL.execution_rows = [
        {
            "id": "run-1",
            "skill_id": "skill-3",
            "workspace_id": "ws-1",
            "schedule_id": None,
            "job_id": "job-1",
            "status": "success",
            "triggered_by": "user-1",
            "started_at": datetime(2026, 3, 19, 12, 0, 0),
            "finished_at": datetime(2026, 3, 19, 12, 0, 4),
            "duration_ms": 4000,
            "message": "Run complete.",
            "error_message": None,
            "result_json": {"ok": True},
            "created_at": datetime(2026, 3, 19, 12, 0, 0),
        }
    ]
    _FakeSkillsSQL.total_rows = [{"cnt": 1}]

    resp = client.get("/api/v1/skills/skill-3/runs", headers=_headers(monkeypatch))

    assert resp.status_code == 200
    row = resp.json["data"][0]
    assert row["id"] == "run-1"
    assert row["duration_ms"] == 4000
    assert row["finished_at"].startswith("2026-03-19T12:00:04")
    assert [event["message"] for event in row["events"]] == [
        "Run queued.",
        "Execution started.",
        "Run complete.",
    ]


def test_skills_runs_alias_marks_successful_skip_as_skipped(client, monkeypatch):
    _install_fake_sql(monkeypatch)
    _FakeSkillsSQL.execution_rows = [
        {
            "id": "run-2",
            "skill_id": "skill-3",
            "workspace_id": "ws-1",
            "schedule_id": None,
            "job_id": "job-2",
            "status": "success",
            "triggered_by": "user-1",
            "started_at": datetime(2026, 3, 19, 12, 5, 0),
            "finished_at": datetime(2026, 3, 19, 12, 5, 1),
            "duration_ms": 1000,
            "message": "Run complete.",
            "error_message": None,
            "result_json": {
                "success": True,
                "message": "No rows returned — webhook skipped (send_if_empty=False).",
                "data": {"skipped": True, "row_count": 0},
                "error": None,
            },
            "created_at": datetime(2026, 3, 19, 12, 5, 0),
        }
    ]
    _FakeSkillsSQL.total_rows = [{"cnt": 1}]

    resp = client.get("/api/v1/skills/skill-3/runs", headers=_headers(monkeypatch))

    assert resp.status_code == 200
    row = resp.json["data"][0]
    assert row["status"] == "skipped"
    assert row["message"] == "No rows returned — webhook skipped (send_if_empty=False)."
    assert row["events"][-1]["status"] == "skipped"
