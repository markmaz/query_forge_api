from __future__ import annotations

import pytest

from app.features.flowforge.runtime.map_transform import FlowForgeMapTransformExecutor
from app.features.flowforge.runtime.map_transform_engine import MapTransformEngine
from app.features.flowforge.runtime.node_executor import FlowForgeNodeExecutionError


class _DataMovementRepo:
    def __init__(self) -> None:
        self.input_artifact = {
            "id": 501,
            "workspace_id": "ws-1",
            "run_id": 90,
            "node_id": "extract",
            "artifact_key": "run:90:node:extract:query_extract",
            "artifact_type": "query_extract",
            "storage_kind": "preview_metadata",
            "storage_ref_json": {
                "columns": [
                    {"key": "patient_email"},
                    {"key": "age"},
                    {"key": "status"},
                ],
                "rows": [
                    {
                        "patient": {"email": "one@example.com"},
                        "age": 34,
                        "status": "active",
                    },
                    {"patient": {"email": ""}, "age": 41, "status": "active"},
                    {
                        "patient": {"email": "three@example.com"},
                        "age": 16,
                        "status": "inactive",
                    },
                ],
            },
            "schema_json": {
                "columns": [{"key": "patient_email"}, {"key": "age"}, {"key": "status"}]
            },
            "row_count": 3,
            "checksum": "sha256:input",
        }
        self.artifacts: list[dict[str, object]] = []
        self.audits: list[dict[str, object]] = []

    def get_dataset_artifact(self, *, workspace_id: str, artifact_id: int):
        if workspace_id == "ws-1" and artifact_id == 501:
            return self.input_artifact
        return None

    def create_dataset_artifact(self, **payload):
        artifact = {**payload, "id": 701}
        self.artifacts.append(artifact)
        return artifact

    def create_data_movement_audit(self, **payload):
        audit = {**payload, "id": 801}
        self.audits.append(audit)
        return audit


def test_map_transform_engine_maps_fields_and_rejects_invalid_rows():
    result = MapTransformEngine().transform(
        rows=[
            {"email": "one@example.com", "age": 34, "status": "active"},
            {"email": "", "age": 41, "status": "active"},
        ],
        config={
            "field_mapping": {"email": "email", "age": "age", "status": "status"},
            "validations": [
                {"field": "email", "rule": "required"},
                {"field": "age", "type": "number"},
                {"field": "status", "rule": "enum", "values": ["active"]},
            ],
        },
    )

    assert result.rows == [{"email": "one@example.com", "age": 34, "status": "active"}]
    assert result.validation_summary["input_row_count"] == 2
    assert result.validation_summary["accepted_row_count"] == 1
    assert result.validation_summary["rejected_row_count"] == 1
    assert result.rejected_rows[0]["errors"][0]["rule"] == "required"


def test_map_transform_executor_creates_transformed_artifact_and_audit():
    data_repo = _DataMovementRepo()
    executor = FlowForgeMapTransformExecutor(data_movement_repository=data_repo)

    result = executor.execute(
        workspace_id="ws-1",
        run_id=90,
        node={
            "id": "transform",
            "type": "map_transform",
            "data": {
                "field_mapping": {
                    "email": "patient.email",
                    "age": "age",
                    "status": "status",
                },
                "validations": [
                    {"field": "email", "rule": "required"},
                    {"field": "age", "type": "number"},
                    {"field": "age", "rule": "min", "value": 18},
                    {"field": "status", "rule": "enum", "values": ["active"]},
                ],
            },
        },
        outgoing_edges=[{"id": "e1", "source": "transform", "target": "export"}],
        run_context={"last_artifact": {"artifact_id": 501}},
    )

    assert result.status == "advance"
    assert result.next_node_id == "export"
    assert result.run_context_update["artifacts"]["transform"]["artifact_id"] == 701
    assert (
        result.event_payload["data_movement"]["validation_summary"][
            "rejected_row_count"
        ]
        == 2
    )
    assert data_repo.artifacts[0]["artifact_type"] == "transform"
    assert data_repo.artifacts[0]["row_count"] == 1
    assert data_repo.artifacts[0]["storage_ref"]["rows"] == [
        {"email": "one@example.com", "age": 34, "status": "active"}
    ]
    assert data_repo.artifacts[0]["schema"]["validation"]["rejected_row_count"] == 2
    assert data_repo.audits[0]["status"] == "completed"
    assert data_repo.audits[0]["source_key"] == "artifact:501"
    assert data_repo.audits[0]["result"]["rejected_row_count"] == 2


def test_map_transform_executor_requires_input_artifact_and_records_failed_audit():
    data_repo = _DataMovementRepo()
    executor = FlowForgeMapTransformExecutor(data_movement_repository=data_repo)

    with pytest.raises(FlowForgeNodeExecutionError) as exc:
        executor.execute(
            workspace_id="ws-1",
            run_id=90,
            node={
                "id": "transform",
                "type": "map_transform",
                "data": {"field_mapping": {"email": "email"}},
            },
            outgoing_edges=[],
            run_context={},
        )

    assert "requires an input artifact" in str(exc.value)
    assert data_repo.artifacts == []
    assert data_repo.audits[0]["status"] == "failed"
