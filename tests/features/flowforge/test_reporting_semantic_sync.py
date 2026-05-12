from __future__ import annotations

import json

from app.features.flowforge.reporting.manifest import REPORTING_DOMAINS
from app.features.flowforge.reporting.semantic_metadata import domain_profile_params
from app.features.flowforge.reporting.semantic_metadata import upsert_generated_semantic_metadata
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

    params = domain_profile_params(workspace_id="ws-1", domain_id=29, domain=domain)

    synonyms = json.loads(params["synonyms"])
    keywords = json.loads(params["keywords"])
    assert any("patient" in item["means"] for item in synonyms)
    assert "patient" in keywords
    assert "client intake" in params["embedding_text"]


def test_flowforge_domain_profile_params_binds_manifest_metrics_to_read_model_columns():
    domain = next(item for item in REPORTING_DOMAINS if item["domain_key"] == "flowforge_workflow_runs")

    params = domain_profile_params(
        workspace_id="ws-1",
        domain_id=29,
        domain=domain,
        workspace_table_id=44,
        columns=[
            {"column_name": "run_id"},
            {"column_name": "completed_flag"},
            {"column_name": "failed_flag"},
            {"column_name": "needs_attention_flag"},
        ],
        column_id_by_name={
            "run_id": 101,
            "completed_flag": 102,
            "failed_flag": 103,
            "needs_attention_flag": 104,
        },
    )

    metrics = {item["metric_key"]: item for item in json.loads(params["metrics"])}

    assert metrics["run_count"]["sql_metric"]["fn"] == "count"
    assert metrics["run_count"]["sql_metric"]["field"]["columnName"] == "run_id"
    assert metrics["completed_run_count"]["sql_metric"]["fn"] == "sum"
    assert metrics["completed_run_count"]["sql_metric"]["field"]["columnName"] == "completed_flag"
    assert metrics["needs_attention_count"]["column_key"] == "wt44.needs_attention_flag"


class _SemanticTx:
    def __init__(self) -> None:
        self.write_calls: list[dict[str, object]] = []

    def execute_query_mappings(self, query, params):
        if "FROM workspace_column" in query:
            return [
                {"id": 101, "column_name": "run_id"},
                {"id": 102, "column_name": "needs_attention_flag"},
                {"id": 103, "column_name": "status"},
            ]
        if "FROM semantic_concept" in query:
            return [{"id": 501}]
        if "FROM semantic_registry" in query:
            return [{"id": 601}]
        return []

    def execute_write(self, query, params):
        self.write_calls.append({"query": query, "params": dict(params or {})})
        return 1


def test_flowforge_semantic_sync_upserts_generated_concepts_registry_and_maps():
    domain = next(item for item in REPORTING_DOMAINS if item["domain_key"] == "flowforge_workflow_runs")
    tx = _SemanticTx()

    result = upsert_generated_semantic_metadata(
        tx,
        workspace_id="ws-1",
        domain=domain,
        workspace_table_id=44,
        columns=[
            {"column_name": "run_id", "data_type": "bigint", "nullable": False, "ordinal_position": 1},
            {"column_name": "needs_attention_flag", "data_type": "int", "nullable": False, "ordinal_position": 2},
            {"column_name": "status", "data_type": "varchar", "nullable": True, "ordinal_position": 3},
        ],
    )

    joined = "\n".join(str(call["query"]) for call in tx.write_calls)
    assert result["semantic_concept_count"] == 3
    assert result["semantic_registry_count"] == 3
    assert result["semantic_concept_map_count"] == 3
    assert result["semantic_column_map_count"] == 3
    assert "INSERT INTO semantic_concept" in joined
    assert "INSERT INTO semantic_registry" in joined
    assert "INSERT INTO workspace_column_semantic_concept_map" in joined
    assert "INSERT INTO semantic_column_map" in joined
    assert "INSERT INTO semantic_concept_alias" in joined
    assert any(call["params"].get("alias_key") == "needs attention" for call in tx.write_calls)
