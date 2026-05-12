from __future__ import annotations

import json

from app.features.flowforge.reporting.manifest import REPORTING_DOMAINS
from app.features.flowforge.reporting.semantic_sync import _domain_profile_params
from app.features.flowforge.reporting.semantic_sync import FlowForgeSemanticSyncService


class _Registry:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def upsert_generated_domain(self, *, workspace_id, domain, actor_user_id):
        self.calls.append(
            {
                "workspace_id": workspace_id,
                "domain_key": domain["domain_key"],
                "actor_user_id": actor_user_id,
            }
        )
        return {"registered": True, "domain_key": domain["domain_key"]}


class _DriftRegistry(_Registry):
    def get_generated_domain_status(self, *, workspace_id, domain):
        return {
            "registration_status": "registration_missing",
            "registration_issues": ["QueryForge generated domain is not registered."],
        }


class _RegisteredRegistry(_Registry):
    def get_generated_domain_status(self, *, workspace_id, domain):
        return {
            "registration_status": "registered",
            "registration_issues": [],
            "domain_id": 101,
            "workspace_table_id": 202,
            "column_count": 12,
        }


def test_flowforge_semantic_sync_dry_run_validates_without_writes():
    registry = _Registry()
    service = FlowForgeSemanticSyncService(registry=registry)

    result = service.sync_domains(workspace_id="ws-1", actor_user_id="admin-1", dry_run=True)

    assert result["status"] == "ok"
    assert result["dry_run"] is True
    assert result["registered_count"] == 0
    assert registry.calls == []
    assert {domain["registration_status"] for domain in result["domains"]} == {"validated"}
    assert result["domains"][0]["queryforge_launch"]["source"] == "flowforge"


def test_flowforge_semantic_sync_dry_run_reports_registry_drift_in_overall_status():
    registry = _DriftRegistry()
    service = FlowForgeSemanticSyncService(registry=registry)

    result = service.sync_domains(workspace_id="ws-1", actor_user_id=None, dry_run=True)

    assert result["status"] == "issues_found"
    assert result["registered_count"] == 0
    assert registry.calls == []
    assert {domain["registration_status"] for domain in result["domains"]} == {"registration_missing"}


def test_flowforge_semantic_sync_dry_run_includes_queryforge_domain_id_in_launch_metadata():
    registry = _RegisteredRegistry()
    service = FlowForgeSemanticSyncService(registry=registry)

    result = service.sync_domains(workspace_id="ws-1", actor_user_id=None, dry_run=True)

    assert result["status"] == "ok"
    assert result["domains"][0]["registration_status"] == "registered"
    assert result["domains"][0]["registration_payload"]["domain_id"] == 101
    assert result["domains"][0]["queryforge_launch"]["domain_id"] == 101


def test_flowforge_semantic_sync_write_mode_upserts_valid_domains():
    registry = _Registry()
    service = FlowForgeSemanticSyncService(registry=registry)

    result = service.sync_domains(workspace_id="ws-1", actor_user_id="admin-1", dry_run=False)

    assert result["status"] == "ok"
    assert result["dry_run"] is False
    assert result["registered_count"] == result["domain_count"]
    assert len(registry.calls) == result["domain_count"]
    assert registry.calls[0]["actor_user_id"] == "admin-1"


def test_flowforge_semantic_sync_reports_missing_read_models():
    service = FlowForgeSemanticSyncService(migration_sql="")

    result = service.sync_domains(workspace_id="ws-1", actor_user_id=None, dry_run=True)

    assert result["status"] == "issues_found"
    assert result["registered_count"] == 0
    assert {domain["registration_status"] for domain in result["domains"]} == {"read_model_missing"}


def test_flowforge_semantic_sync_reports_sensitive_drift():
    service = FlowForgeSemanticSyncService(
        migration_sql="""
        CREATE OR REPLACE VIEW v_flowforge_report_workflow_runs AS
        SELECT
          id AS run_id,
          workspace_id,
          workflow_definition_id,
          workflow_version_id,
          workflow_key,
          intake_event_id,
          mode,
          status,
          workflow_lifecycle,
          run_as_principal_type,
          started_at,
          completed_at,
          failed_at,
          created_at,
          updated_at,
          run_context_json
        FROM flowforge_runs;
        """
    )

    result = service.sync_domains(workspace_id="ws-1", actor_user_id=None, dry_run=True)

    workflow_runs = next(domain for domain in result["domains"] if domain["domain_key"] == "flowforge_workflow_runs")
    assert workflow_runs["registration_status"] == "sensitive_mismatch"
    assert any("sensitive field run_context_json" in issue for issue in workflow_runs["registration_issues"])


def test_flowforge_domain_profile_params_embeds_manifest_synonyms():
    domain = next(item for item in REPORTING_DOMAINS if item["domain_key"] == "flowforge_intake_events")

    params = _domain_profile_params(workspace_id="ws-1", domain_id=29, domain=domain)

    synonyms = json.loads(params["synonyms"])
    keywords = json.loads(params["keywords"])
    assert any("patient" in item["means"] for item in synonyms)
    assert "patient" in keywords
    assert "client intake" in params["embedding_text"]
