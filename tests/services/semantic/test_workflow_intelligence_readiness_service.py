from __future__ import annotations

import json
from typing import Any

from app.services.semantic.workflow_intelligence_readiness_service import WorkflowIntelligenceSemanticReadinessService


class _FakeSQL:
    def __init__(self, *, counts: dict[str, int] | None = None, metrics: list[dict[str, Any]] | None = None) -> None:
        self._counts = counts or {
            "generated_concept_count": 8,
            "generated_registry_count": 8,
            "concept_column_map_count": 8,
            "semantic_column_map_count": 8,
            "alias_count": 12,
        }
        self._metrics = metrics or [
            {"metric_key": "run_count", "column_key": "wt44.run_id", "sql_metric": {"fn": "count"}},
            {"metric_key": "completed_run_count", "column_key": "wt44.completed_flag", "sql_metric": {"fn": "sum"}},
            {"metric_key": "failed_run_count", "column_key": "wt44.failed_flag", "sql_metric": {"fn": "sum"}},
            {
                "metric_key": "needs_attention_count",
                "column_key": "wt44.needs_attention_flag",
                "sql_metric": {"fn": "sum"},
            },
            {"metric_key": "active_run_count", "column_key": "wt44.started_at", "sql_metric": {"fn": "count"}},
        ]

    def execute_query_mappings(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if "FROM domain_profile" in query:
            return [{"metrics": json.dumps(self._metrics)}]
        return [dict(self._counts)]


class _FakeSyncService:
    def __init__(self, *, registered: bool = True) -> None:
        self.sync_calls: list[dict[str, Any]] = []
        self._registered = registered

    def sync_domains(self, *, workspace_id: str, actor_user_id: str | None, dry_run: bool) -> dict[str, Any]:
        self.sync_calls.append({"workspace_id": workspace_id, "actor_user_id": actor_user_id, "dry_run": dry_run})
        if not dry_run:
            return {"workspace_id": workspace_id, "dry_run": False, "status": "ok", "registered_count": 1, "domains": []}
        registration_status = "registered" if self._registered else "registration_missing"
        registration_issues = [] if self._registered else ["QueryForge generated domain is not registered."]
        return {
            "workspace_id": workspace_id,
            "dry_run": True,
            "domains": [
                {
                    "domain_key": "flowforge_workflow_runs",
                    "read_model": "v_flowforge_report_workflow_runs",
                    "registration_status": registration_status,
                    "registration_issues": registration_issues,
                    "registration_payload": {"domain_id": 29, "workspace_table_id": 44, "column_count": 18},
                }
            ],
        }


def test_workflow_intelligence_readiness_reports_ready_semantic_tables():
    service = WorkflowIntelligenceSemanticReadinessService(sql=_FakeSQL(), sync_service=_FakeSyncService())

    result = service.get_readiness(workspace_id="ws-1")

    assert result["status"] == "ready"
    assert result["summary"]["ready_domain_count"] == 1
    assert result["summary"]["generated_concept_count"] == 8
    assert result["summary"]["bound_metric_count"] == 5
    assert result["domains"][0]["metric_bindings"]["bound_metrics"] == [
        "run_count",
        "active_run_count",
        "completed_run_count",
        "failed_run_count",
        "needs_attention_count",
    ]


def test_workflow_intelligence_readiness_surfaces_missing_metric_bindings():
    service = WorkflowIntelligenceSemanticReadinessService(
        sql=_FakeSQL(metrics=[{"metric_key": "run_count", "column_key": "wt44.run_id"}]),
        sync_service=_FakeSyncService(),
    )

    result = service.get_readiness(workspace_id="ws-1")

    assert result["status"] == "needs_attention"
    assert result["summary"]["missing_metric_binding_count"] == 0
    assert result["summary"]["issue_domain_count"] == 1
    assert "active_run_count" in result["domains"][0]["metric_bindings"]["missing_metrics"]
    assert any("missing generated metrics" in issue for issue in result["domains"][0]["issues"])


def test_workflow_intelligence_readiness_points_unbound_metrics_to_migrations():
    metrics = [
        {"metric_key": "run_count", "column_key": "wt44.run_id"},
        {"metric_key": "active_run_count"},
        {"metric_key": "completed_run_count", "column_key": "wt44.completed_flag"},
        {"metric_key": "failed_run_count", "column_key": "wt44.failed_flag"},
        {"metric_key": "needs_attention_count", "column_key": "wt44.needs_attention_flag"},
    ]
    service = WorkflowIntelligenceSemanticReadinessService(
        sql=_FakeSQL(metrics=metrics),
        sync_service=_FakeSyncService(),
    )

    result = service.get_readiness(workspace_id="ws-1")

    assert result["status"] == "needs_attention"
    assert result["summary"]["missing_metric_binding_count"] == 1
    assert result["domains"][0]["metric_bindings"]["unbound_metrics"] == ["active_run_count"]
    assert "metric-flag read-model migration" in result["domains"][0]["suggested_action"]


def test_workflow_intelligence_readiness_sync_delegates_to_semantic_sync():
    sync_service = _FakeSyncService()
    service = WorkflowIntelligenceSemanticReadinessService(sql=_FakeSQL(), sync_service=sync_service)

    result = service.sync_readiness(workspace_id="ws-1", actor_user_id="admin-1")

    assert result["registered_count"] == 1
    assert sync_service.sync_calls == [{"workspace_id": "ws-1", "actor_user_id": "admin-1", "dry_run": False}]
