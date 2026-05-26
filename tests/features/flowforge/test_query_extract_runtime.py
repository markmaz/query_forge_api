from __future__ import annotations

import pytest

from app.features.flowforge.runtime.artifacts import DatasetArtifactMetadataBuilder
from app.features.flowforge.runtime.node_executor import FlowForgeNodeExecutionError
from app.features.flowforge.runtime.query_extract import FlowForgeQueryExtractExecutor
from app.features.flowforge.runtime.query_extract_sources import (
    QueryExtractResult,
    QueryExtractSource,
    QueryForgeSavedQueryExtractResolver,
)


class _DataMovementRepo:
    def __init__(self) -> None:
        self.artifacts: list[dict[str, object]] = []
        self.audits: list[dict[str, object]] = []

    def create_dataset_artifact(self, **payload):
        artifact = {**payload, "id": 501}
        self.artifacts.append(artifact)
        return artifact

    def create_data_movement_audit(self, **payload):
        audit = {**payload, "id": 601}
        self.audits.append(audit)
        return audit


class _Resolver:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def execute_preview(
        self, *, workspace_id: str, node_config: dict, preview_limit: int
    ):
        self.calls.append(
            {
                "workspace_id": workspace_id,
                "node_config": node_config,
                "preview_limit": preview_limit,
            }
        )
        return QueryExtractResult(
            rows=[
                {"patient_email": "one@example.com", "status": "active"},
                {"patient_email": "two@example.com", "status": "pending"},
            ],
            columns=[
                {"key": "patient_email", "label": "Patient Email"},
                {"key": "status", "label": "Status"},
            ],
            total=2,
            source=QueryExtractSource(
                source_kind="saved_query",
                source_id="saved-1",
                display_name="Active Patients",
                descriptor={"saved_query_id": "saved-1"},
            ),
        )


def test_query_extract_executor_runs_governed_preview_and_creates_artifact_and_audit():
    data_repo = _DataMovementRepo()
    resolver = _Resolver()
    executor = FlowForgeQueryExtractExecutor(
        data_movement_repository=data_repo, resolver=resolver
    )

    result = executor.execute(
        workspace_id="ws-1",
        run_id=90,
        node={
            "id": "extract",
            "type": "query_extract",
            "data": {"saved_query_id": "saved-1", "preview_limit": 1000},
        },
        outgoing_edges=[{"id": "e1", "source": "extract", "target": "approve"}],
        run_context={},
    )

    assert resolver.calls[0]["preview_limit"] == 1000
    assert result.status == "advance"
    assert result.next_node_id == "approve"
    assert result.run_context_update["artifacts"]["extract"]["artifact_id"] == 501
    assert data_repo.artifacts[0]["artifact_type"] == "query_extract"
    assert data_repo.artifacts[0]["row_count"] == 2
    assert str(data_repo.artifacts[0]["checksum"]).startswith("sha256:")
    assert (
        data_repo.artifacts[0]["schema"]["sensitivity"]["classification"]
        == "possible_sensitive"
    )
    assert data_repo.audits[0]["status"] == "completed"
    assert data_repo.audits[0]["request"] == {
        "source_kind": "saved_query",
        "source_id": "saved-1",
        "preview_limit": 1000,
    }
    assert data_repo.audits[0]["result"]["artifact_id"] == 501


def test_query_extract_executor_uses_configurable_default_and_max_limits():
    data_repo = _DataMovementRepo()
    resolver = _Resolver()
    executor = FlowForgeQueryExtractExecutor(
        data_movement_repository=data_repo,
        resolver=resolver,
        default_preview_limit=25,
        max_preview_limit=250,
    )

    executor.execute(
        workspace_id="ws-1",
        run_id=90,
        node={
            "id": "extract",
            "type": "query_extract",
            "data": {"saved_query_id": "saved-1"},
        },
        outgoing_edges=[],
        run_context={},
    )

    assert resolver.calls[0]["preview_limit"] == 25

    executor.execute(
        workspace_id="ws-1",
        run_id=91,
        node={
            "id": "extract",
            "type": "query_extract",
            "data": {"saved_query_id": "saved-1", "preview_limit": 1000},
        },
        outgoing_edges=[],
        run_context={},
    )

    assert resolver.calls[1]["preview_limit"] == 250

    executor.execute(
        workspace_id="ws-1",
        run_id=92,
        node={
            "id": "extract",
            "type": "query_extract",
            "data": {"saved_query_id": "saved-1", "preview_limit": "max"},
        },
        outgoing_edges=[],
        run_context={},
    )

    assert resolver.calls[2]["preview_limit"] == 250


def test_query_extract_executor_rejects_max_without_configured_limit():
    executor = FlowForgeQueryExtractExecutor(
        data_movement_repository=_DataMovementRepo(),
        resolver=_Resolver(),
        max_preview_limit=0,
    )

    with pytest.raises(FlowForgeNodeExecutionError) as exc:
        executor.execute(
            workspace_id="ws-1",
            run_id=90,
            node={
                "id": "extract",
                "type": "query_extract",
                "data": {"saved_query_id": "saved-1", "preview_limit": "max"},
            },
            outgoing_edges=[],
            run_context={},
        )

    assert "FLOWFORGE_QUERY_EXTRACT_MAX_LIMIT" in str(exc.value)


def test_query_extract_executor_rejects_raw_sql_fields_before_resolution():
    data_repo = _DataMovementRepo()
    resolver = _Resolver()
    executor = FlowForgeQueryExtractExecutor(
        data_movement_repository=data_repo, resolver=resolver
    )

    with pytest.raises(FlowForgeNodeExecutionError) as exc:
        executor.execute(
            workspace_id="ws-1",
            run_id=90,
            node={
                "id": "extract",
                "type": "query_extract",
                "data": {"raw_sql": "select * from x", "saved_query_id": "saved-1"},
            },
            outgoing_edges=[],
            run_context={},
        )

    assert "cannot define raw SQL fields: raw_sql" in str(exc.value)
    assert resolver.calls == []
    assert data_repo.artifacts == []
    assert data_repo.audits[0]["status"] == "failed"


def test_query_extract_executor_records_failed_audit():
    data_repo = _DataMovementRepo()
    executor = FlowForgeQueryExtractExecutor(
        data_movement_repository=data_repo, resolver=_Resolver()
    )

    executor.record_failed_audit(
        workspace_id="ws-1",
        run_id=90,
        node={
            "id": "extract",
            "type": "query_extract",
            "data": {"saved_query_id": "saved-1"},
        },
        error_message="resolver failed",
    )

    assert data_repo.audits[0]["status"] == "failed"
    assert data_repo.audits[0]["source_key"] == "saved-1"
    assert data_repo.audits[0]["error_message"] == "resolver failed"


def test_artifact_metadata_checksum_is_stable_for_same_payload():
    builder = DatasetArtifactMetadataBuilder()
    first = builder.build_query_extract_metadata(
        rows=[{"id": 1, "name": "A"}],
        columns=[{"key": "id"}, {"key": "name"}],
        source={"saved_query_id": "saved-1"},
        preview_limit=100,
    )
    second = builder.build_query_extract_metadata(
        rows=[{"id": 1, "name": "A"}],
        columns=[{"key": "id"}, {"key": "name"}],
        source={"saved_query_id": "saved-1"},
        preview_limit=100,
    )

    assert first["checksum"] == second["checksum"]
    assert first["schema"]["sensitivity"]["classification"] == "unclassified"


def test_saved_query_extract_resolver_uses_governed_queryforge_preview(monkeypatch):
    class _Sql:
        def execute_query_mappings(self, query, params=None):
            assert "FROM saved_query" in query
            assert params == {"saved_query_id": "saved-1", "workspace_id": "ws-1"}
            return [{"sql_json": '{"columns":[{"key":"id"}]}', "title": "Saved One"}]

    class _ContextBuilder:
        def build(self, workspace_id: str):
            assert workspace_id == "ws-1"
            return type("_Context", (), {"sql_exec": object()})()

    class _QueryForgeService:
        def __init__(self, *, executor, domain_resolver):
            self.executor = executor
            self.domain_resolver = domain_resolver

        def run(self, sql_json, *, mode: str, limit: int, offset: int):
            assert sql_json == {"columns": [{"key": "id"}]}
            assert mode == "preview"
            assert limit == 25
            assert offset == 0
            return type(
                "_Result",
                (),
                {
                    "rows": [{"id": 1}],
                    "columns": [{"key": "id"}],
                    "total": 1,
                },
            )()

    monkeypatch.setattr(
        "app.features.flowforge.runtime.query_extract_sources.QueryForgeService",
        _QueryForgeService,
    )

    resolver = QueryForgeSavedQueryExtractResolver(
        sql=_Sql(), context_builder=_ContextBuilder()
    )

    result = resolver.execute_preview(
        workspace_id="ws-1",
        node_config={"saved_query_id": "saved-1"},
        preview_limit=25,
    )

    assert result.source.source_kind == "saved_query"
    assert result.source.display_name == "Saved One"
    assert result.rows == [{"id": 1}]
