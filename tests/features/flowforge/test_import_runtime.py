from __future__ import annotations

import json

import pytest

from app.features.flowforge.runtime.data_import import FlowForgeImportExecutor
from app.features.flowforge.runtime.import_sources import LocalFileTestImportAdapter
from app.features.flowforge.runtime.node_executor import FlowForgeNodeExecutionError


class _DataMovementRepo:
    def __init__(self, *, source_enabled: bool = True) -> None:
        self.source = {
            "id": 11,
            "workspace_id": "ws-1",
            "source_key": "local-import",
            "display_name": "Local Import",
            "source_type": "local_file_test",
            "enabled": source_enabled,
            "mode": "test",
            "config_json": {},
        }
        self.artifacts: list[dict[str, object]] = []
        self.audits: list[dict[str, object]] = []

    def get_data_source_by_key(self, *, workspace_id: str, source_key: str):
        if workspace_id == "ws-1" and source_key == "local-import":
            return self.source
        return None

    def create_dataset_artifact(self, **payload):
        artifact = {**payload, "id": 701}
        self.artifacts.append(artifact)
        return artifact

    def create_data_movement_audit(self, **payload):
        audit = {**payload, "id": 801}
        self.audits.append(audit)
        return audit


class _ResourceRepo:
    def __init__(self) -> None:
        self.batches = []
        self.records = []
        self.completed = []
        self.activated = []

    def get_resource_set(self, *, workspace_id: str, resource_set_id: int):
        if workspace_id == "ws-1" and resource_set_id == 20:
            return {"id": 20, "workspace_id": workspace_id}
        return None

    def create_snapshot_batch(self, **payload):
        self.batches.append(payload)
        return 901

    def upsert_snapshot_record(self, **payload):
        self.records.append(payload)
        return 1000 + len(self.records)

    def complete_snapshot_batch(self, **payload):
        self.completed.append(payload)
        return True

    def activate_snapshot_batch(self, **payload):
        self.activated.append(payload)
        return True


def test_local_file_test_import_adapter_reads_csv(tmp_path):
    source_file = tmp_path / "resources.csv"
    source_file.write_text("source_record_key,display_name\nr1,Jane\n", encoding="utf-8")

    result = LocalFileTestImportAdapter().read(
        source={
            "source_key": "local-import",
            "source_type": "local_file_test",
            "mode": "test",
            "config_json": {"base_dir": str(tmp_path)},
        },
        config={"filename": "resources.csv"},
    )

    assert result.rows == [{"source_record_key": "r1", "display_name": "Jane"}]
    assert result.columns == [
        {"key": "source_record_key", "label": "Source Record Key"},
        {"key": "display_name", "label": "Display Name"},
    ]
    assert result.byte_count == source_file.stat().st_size
    assert result.checksum.startswith("sha256:")


def test_local_file_test_import_adapter_reads_json_records(tmp_path):
    source_file = tmp_path / "resources.json"
    source_file.write_text(json.dumps({"records": [{"source_record_key": "r1"}]}), encoding="utf-8")

    result = LocalFileTestImportAdapter().read(
        source={
            "source_key": "local-import",
            "source_type": "local_file_test",
            "mode": "test",
            "config_json": {"base_dir": str(tmp_path)},
        },
        config={"filename": "resources.json"},
    )

    assert result.rows == [{"source_record_key": "r1"}]


def test_import_executor_stages_artifact_and_activates_valid_resource_set_rows(tmp_path):
    source_file = tmp_path / "resources.csv"
    source_file.write_text(
        "source_record_key,display_name,capacity_total,capacity_used\nr1,Jane,5,2\n",
        encoding="utf-8",
    )
    data_repo = _DataMovementRepo()
    data_repo.source["config_json"] = {"base_dir": str(tmp_path)}
    resource_repo = _ResourceRepo()
    executor = FlowForgeImportExecutor(
        data_movement_repository=data_repo,
        resource_repository=resource_repo,
    )

    result = executor.execute(
        workspace_id="ws-1",
        run_id=90,
        node={
            "id": "import",
            "type": "import",
            "data": {
                "source_key": "local-import",
                "filename": "resources.csv",
                "resource_set_id": 20,
                "activate": True,
            },
        },
        outgoing_edges=[{"id": "e1", "source": "import", "target": "done"}],
        run_context={},
    )

    assert result.status == "advance"
    assert result.next_node_id == "done"
    assert result.run_context_update["artifacts"]["import"]["artifact_id"] == 701
    assert data_repo.artifacts[0]["artifact_type"] == "import"
    assert data_repo.artifacts[0]["status"] == "staged"
    assert data_repo.artifacts[0]["schema"]["validation"]["invalid_row_count"] == 0
    assert data_repo.audits[0]["status"] == "completed"
    assert data_repo.audits[0]["resource_set_id"] == 20
    assert data_repo.audits[0]["result"]["activation"]["snapshot_batch_id"] == 901
    assert resource_repo.records[0]["source_record_key"] == "r1"
    assert resource_repo.records[0]["capacity_available"] == 3
    assert resource_repo.activated[0]["snapshot_batch_id"] == 901


def test_import_executor_reports_invalid_rows_without_activation(tmp_path):
    source_file = tmp_path / "resources.csv"
    source_file.write_text("display_name\nMissing Key\n", encoding="utf-8")
    data_repo = _DataMovementRepo()
    data_repo.source["config_json"] = {"base_dir": str(tmp_path)}
    resource_repo = _ResourceRepo()
    executor = FlowForgeImportExecutor(
        data_movement_repository=data_repo,
        resource_repository=resource_repo,
    )

    with pytest.raises(FlowForgeNodeExecutionError) as exc:
        executor.execute(
            workspace_id="ws-1",
            run_id=90,
            node={
                "id": "import",
                "type": "import",
                "data": {
                    "source_key": "local-import",
                    "filename": "resources.csv",
                    "resource_set_id": 20,
                    "activate": True,
                },
            },
            outgoing_edges=[],
            run_context={},
        )

    assert "invalid rows" in str(exc.value)
    assert data_repo.artifacts[0]["status"] == "validation_failed"
    assert data_repo.artifacts[0]["schema"]["validation"]["invalid_row_count"] == 1
    assert data_repo.audits[0]["status"] == "failed"
    assert resource_repo.records == []
    assert resource_repo.activated == []


def test_import_executor_rejects_disabled_sources_and_records_failed_audit(tmp_path):
    data_repo = _DataMovementRepo(source_enabled=False)
    data_repo.source["config_json"] = {"base_dir": str(tmp_path)}
    executor = FlowForgeImportExecutor(data_movement_repository=data_repo)

    with pytest.raises(FlowForgeNodeExecutionError) as exc:
        executor.execute(
            workspace_id="ws-1",
            run_id=90,
            node={
                "id": "import",
                "type": "import",
                "data": {"source_key": "local-import", "filename": "missing.csv"},
            },
            outgoing_edges=[],
            run_context={},
        )

    assert "is disabled" in str(exc.value)
    assert data_repo.artifacts == []
    assert data_repo.audits[0]["status"] == "failed"
