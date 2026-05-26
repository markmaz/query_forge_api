from __future__ import annotations

from pathlib import Path

import pytest

from app.features.flowforge.runtime.export import FlowForgeExportExecutor
from app.features.flowforge.runtime.export_adapters import LocalFileTestExportAdapter
from app.features.flowforge.runtime.export_policy import ExportPolicyEvaluator
from app.features.flowforge.runtime.node_executor import FlowForgeNodeExecutionError


class _DataMovementRepo:
    def __init__(
        self, *, base_dir: Path, enabled: bool = True, policy: dict | None = None
    ) -> None:
        self.input_artifact = {
            "id": 601,
            "workspace_id": "ws-1",
            "run_id": 90,
            "node_id": "transform",
            "artifact_key": "run:90:node:transform:map_transform",
            "artifact_type": "transform",
            "storage_kind": "preview_metadata",
            "storage_ref_json": {
                "columns": [{"key": "email"}, {"key": "status"}],
                "rows": [
                    {"email": "one@example.com", "status": "active"},
                    {"email": "two@example.com", "status": "pending"},
                ],
            },
            "schema_json": {
                "columns": [{"key": "email"}, {"key": "status"}],
                "sensitivity": {"classification": "possible_sensitive"},
            },
            "row_count": 2,
            "checksum": "sha256:input",
        }
        self.destination = {
            "id": 11,
            "workspace_id": "ws-1",
            "destination_key": "local-test",
            "display_name": "Local Test",
            "destination_type": "local_file_test",
            "enabled": enabled,
            "mode": "test",
            "config_json": {"base_dir": str(base_dir), "export_policy": policy or {}},
        }
        self.artifacts: list[dict[str, object]] = []
        self.audits: list[dict[str, object]] = []

    def get_dataset_artifact(self, *, workspace_id: str, artifact_id: int):
        if workspace_id == "ws-1" and artifact_id == 601:
            return self.input_artifact
        return None

    def get_data_destination_by_key(self, *, workspace_id: str, destination_key: str):
        if workspace_id == "ws-1" and destination_key == "local-test":
            return self.destination
        return None

    def create_dataset_artifact(self, **payload):
        artifact = {**payload, "id": 901}
        self.artifacts.append(artifact)
        return artifact

    def create_data_movement_audit(self, **payload):
        audit = {**payload, "id": 1001}
        self.audits.append(audit)
        return audit


def test_local_file_test_export_adapter_writes_csv(tmp_path):
    result = LocalFileTestExportAdapter().write(
        rows=[{"email": "one@example.com", "status": "active"}],
        columns=[{"key": "email"}, {"key": "status"}],
        destination={
            "destination_key": "local-test",
            "destination_type": "local_file_test",
            "config_json": {"base_dir": str(tmp_path)},
        },
        config={"filename": "patients.csv"},
        run_id=90,
        node_id="export",
    )

    output = tmp_path / "patients.csv"
    assert (
        output.read_text(encoding="utf-8") == "email,status\none@example.com,active\n"
    )
    assert result.row_count == 1
    assert result.byte_count == output.stat().st_size
    assert result.checksum.startswith("sha256:")
    assert result.destination_ref["path"] == str(output)


def test_export_executor_writes_to_enabled_allowlisted_destination_and_audits(tmp_path):
    data_repo = _DataMovementRepo(base_dir=tmp_path)
    executor = FlowForgeExportExecutor(data_movement_repository=data_repo)

    result = executor.execute(
        workspace_id="ws-1",
        run_id=90,
        node={
            "id": "export",
            "type": "export",
            "data": {"destination_key": "local-test", "filename": "out.csv"},
        },
        outgoing_edges=[{"id": "e1", "source": "export", "target": "approve"}],
        run_context={"last_artifact": {"artifact_id": 601}},
    )

    assert result.status == "advance"
    assert result.next_node_id == "approve"
    assert result.run_context_update["artifacts"]["export"]["artifact_id"] == 901
    assert (tmp_path / "out.csv").exists()
    assert data_repo.artifacts[0]["artifact_type"] == "export_payload"
    assert data_repo.artifacts[0]["row_count"] == 2
    assert data_repo.artifacts[0]["byte_count"] == (tmp_path / "out.csv").stat().st_size
    assert data_repo.audits[0]["status"] == "completed"
    assert data_repo.audits[0]["destination_key"] == "local-test"
    assert data_repo.audits[0]["result"]["row_count"] == 2
    assert data_repo.audits[0]["result"]["export_policy"]["allowed"] is True


def test_export_executor_rejects_disabled_destinations_and_records_failed_audit(
    tmp_path,
):
    data_repo = _DataMovementRepo(base_dir=tmp_path, enabled=False)
    executor = FlowForgeExportExecutor(data_movement_repository=data_repo)

    with pytest.raises(FlowForgeNodeExecutionError) as exc:
        executor.execute(
            workspace_id="ws-1",
            run_id=90,
            node={
                "id": "export",
                "type": "export",
                "data": {"destination_key": "local-test"},
            },
            outgoing_edges=[],
            run_context={"last_artifact": {"artifact_id": 601}},
        )

    assert "is disabled" in str(exc.value)
    assert data_repo.artifacts == []
    assert data_repo.audits[0]["status"] == "failed"


def test_export_policy_blocks_sensitive_payloads_when_destination_policy_requires_it(
    tmp_path,
):
    data_repo = _DataMovementRepo(base_dir=tmp_path, policy={"block_sensitive": True})
    executor = FlowForgeExportExecutor(data_movement_repository=data_repo)

    with pytest.raises(FlowForgeNodeExecutionError) as exc:
        executor.execute(
            workspace_id="ws-1",
            run_id=90,
            node={
                "id": "export",
                "type": "export",
                "data": {"destination_key": "local-test"},
            },
            outgoing_edges=[],
            run_context={"last_artifact": {"artifact_id": 601}},
        )

    assert "sensitive_export_blocked" in str(exc.value)
    assert not any(tmp_path.iterdir())


def test_export_policy_evaluator_enforces_row_count_limit():
    result = ExportPolicyEvaluator().evaluate(
        artifact={"schema_json": {"sensitivity": {"classification": "unclassified"}}},
        destination={"config_json": {"export_policy": {"max_rows": 1}}},
        row_count=2,
    )

    assert result["allowed"] is False
    assert result["reason"] == "row_count_exceeds_policy"
