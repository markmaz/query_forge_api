from __future__ import annotations

from typing import Any

from app.features.flowforge.repositories import FlowForgeDataMovementRepository
from app.features.flowforge.runtime.artifacts import DatasetArtifactMetadataBuilder
from app.features.flowforge.runtime.dataset_artifact_io import (
    InlineDatasetArtifactReader,
)
from app.features.flowforge.runtime.map_transform_engine import MapTransformEngine
from app.features.flowforge.runtime.node_executor import (
    FlowForgeNodeExecutionError,
    NodeExecutionResult,
)


class FlowForgeMapTransformExecutor:
    def __init__(
        self,
        *,
        data_movement_repository: FlowForgeDataMovementRepository | None = None,
        transform_engine: MapTransformEngine | None = None,
        artifact_metadata_builder: DatasetArtifactMetadataBuilder | None = None,
        artifact_reader: InlineDatasetArtifactReader | None = None,
    ) -> None:
        self._data_movement_repository = (
            data_movement_repository or FlowForgeDataMovementRepository()
        )
        self._transform_engine = transform_engine or MapTransformEngine()
        self._artifact_metadata_builder = (
            artifact_metadata_builder or DatasetArtifactMetadataBuilder()
        )
        self._artifact_reader = artifact_reader or InlineDatasetArtifactReader()

    def execute(
        self,
        *,
        workspace_id: str,
        run_id: int,
        node: dict[str, Any],
        outgoing_edges: list[dict[str, Any]],
        run_context: dict[str, Any],
    ) -> NodeExecutionResult:
        node_id = str(node.get("id") or "").strip()
        config = self._node_config(node)
        try:
            input_artifact = self._resolve_input_artifact(
                workspace_id=workspace_id, config=config, run_context=run_context
            )
            rows = self._artifact_reader.rows(input_artifact)
            result = self._transform_engine.transform(rows=rows, config=config)
        except FlowForgeNodeExecutionError as exc:
            self._record_failed_audit_safely(
                workspace_id=workspace_id,
                run_id=run_id,
                node=node,
                error_message=str(exc),
            )
            raise
        except Exception as exc:
            self._record_failed_audit_safely(
                workspace_id=workspace_id,
                run_id=run_id,
                node=node,
                error_message=str(exc),
            )
            raise FlowForgeNodeExecutionError(str(exc)) from exc

        metadata = self._artifact_metadata_builder.build_transform_metadata(
            rows=result.rows,
            columns=result.columns,
            input_artifact=input_artifact,
            validation_summary=result.validation_summary,
        )
        artifact_key = str(
            config.get("output_artifact_key") or config.get("artifact_key") or ""
        ).strip()
        if not artifact_key:
            artifact_key = f"run:{int(run_id)}:node:{node_id}:map_transform"
        artifact = self._data_movement_repository.create_dataset_artifact(
            workspace_id=workspace_id,
            run_id=run_id,
            node_id=node_id,
            artifact_key=artifact_key,
            artifact_type="transform",
            storage_kind="preview_metadata",
            storage_ref=metadata["storage_ref"],
            schema=metadata["schema"],
            row_count=metadata["row_count"],
            byte_count=None,
            checksum=metadata["checksum"],
            status="ready",
            expires_at=None,
            created_by="flowforge",
        )
        self._data_movement_repository.create_data_movement_audit(
            workspace_id=workspace_id,
            run_id=run_id,
            node_id=node_id,
            action_type="map_transform",
            status="completed",
            source_key=f"artifact:{int(input_artifact['id'])}",
            destination_key=None,
            dataset_artifact_id=int(artifact["id"]),
            resource_set_id=None,
            actor_type="system",
            actor_id="flowforge",
            request={
                "input_artifact_id": int(input_artifact["id"]),
                "field_mapping_count": self._field_mapping_count(
                    config.get("field_mapping") or config.get("mapping")
                ),
                "validation_count": result.validation_summary["validation_count"],
            },
            result={
                "artifact_id": int(artifact["id"]),
                "row_count": metadata["row_count"],
                "rejected_row_count": result.validation_summary["rejected_row_count"],
                "checksum": metadata["checksum"],
            },
            error_message=None,
            idempotency_key=f"{artifact_key}:audit",
            completed_at=None,
        )
        artifact_ref = {
            "artifact_id": int(artifact["id"]),
            "artifact_key": artifact_key,
            "artifact_type": "transform",
            "node_id": node_id,
            "row_count": metadata["row_count"],
            "rejected_row_count": result.validation_summary["rejected_row_count"],
            "checksum": metadata["checksum"],
        }
        next_node_id = self._first_target(outgoing_edges)
        return NodeExecutionResult(
            status="advance" if next_node_id else "completed",
            next_node_id=next_node_id,
            event_payload={
                "node_type": "map_transform",
                "next_node_id": next_node_id,
                "data_movement": {
                    "node_type": "map_transform",
                    "execution_status": "completed",
                    "input_artifact_id": int(input_artifact["id"]),
                    "artifact": artifact_ref,
                    "validation_summary": result.validation_summary,
                },
            },
            run_context_update={
                "artifacts": {node_id: artifact_ref},
                "last_artifact": artifact_ref,
            },
        )

    def _resolve_input_artifact(
        self,
        *,
        workspace_id: str,
        config: dict[str, Any],
        run_context: dict[str, Any],
    ) -> dict[str, Any]:
        artifact_id = self._input_artifact_id(config=config, run_context=run_context)
        if artifact_id is None:
            raise FlowForgeNodeExecutionError(
                "map_transform requires an input artifact."
            )
        artifact = self._data_movement_repository.get_dataset_artifact(
            workspace_id=workspace_id, artifact_id=artifact_id
        )
        if artifact is None:
            raise FlowForgeNodeExecutionError(
                f"Input artifact '{artifact_id}' was not found."
            )
        return artifact

    def _input_artifact_id(
        self, *, config: dict[str, Any], run_context: dict[str, Any]
    ) -> int | None:
        if config.get("input_artifact_id") is not None:
            return int(config["input_artifact_id"])
        input_node_id = str(config.get("input_node_id") or "").strip()
        artifacts = (
            run_context.get("artifacts")
            if isinstance(run_context.get("artifacts"), dict)
            else {}
        )
        if input_node_id and isinstance(artifacts, dict):
            artifact_ref = artifacts.get(input_node_id)
            if (
                isinstance(artifact_ref, dict)
                and artifact_ref.get("artifact_id") is not None
            ):
                return int(artifact_ref["artifact_id"])
        last_artifact = run_context.get("last_artifact")
        if (
            isinstance(last_artifact, dict)
            and last_artifact.get("artifact_id") is not None
        ):
            return int(last_artifact["artifact_id"])
        return None

    def _record_failed_audit_safely(
        self,
        *,
        workspace_id: str,
        run_id: int,
        node: dict[str, Any],
        error_message: str,
    ) -> None:
        try:
            self.record_failed_audit(
                workspace_id=workspace_id,
                run_id=run_id,
                node=node,
                error_message=error_message,
            )
        except Exception:
            return

    def record_failed_audit(
        self,
        *,
        workspace_id: str,
        run_id: int,
        node: dict[str, Any],
        error_message: str,
    ) -> None:
        node_id = str(node.get("id") or "").strip()
        self._data_movement_repository.create_data_movement_audit(
            workspace_id=workspace_id,
            run_id=run_id,
            node_id=node_id,
            action_type="map_transform",
            status="failed",
            source_key=None,
            destination_key=None,
            dataset_artifact_id=None,
            resource_set_id=None,
            actor_type="system",
            actor_id="flowforge",
            request={"node_id": node_id},
            result=None,
            error_message=error_message,
            idempotency_key=f"run:{int(run_id)}:node:{node_id}:map_transform:audit:failed",
            completed_at=None,
        )

    @staticmethod
    def _node_config(node: dict[str, Any]) -> dict[str, Any]:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        return {**data, **config}

    @staticmethod
    def _field_mapping_count(field_mapping: Any) -> int:
        if isinstance(field_mapping, dict | list):
            return len(field_mapping)
        return 0

    @staticmethod
    def _first_target(outgoing_edges: list[dict[str, Any]]) -> str | None:
        for edge in sorted(outgoing_edges, key=lambda row: str(row.get("id") or "")):
            target = str(edge.get("target") or "").strip()
            if target:
                return target
        return None
