from __future__ import annotations

from typing import Any

from app.features.flowforge.repositories import FlowForgeDataMovementRepository
from app.features.flowforge.runtime.dataset_artifact_io import (
    InlineDatasetArtifactReader,
)
from app.features.flowforge.runtime.export_adapters import LocalFileTestExportAdapter
from app.features.flowforge.runtime.export_policy import ExportPolicyEvaluator
from app.features.flowforge.runtime.node_executor import (
    FlowForgeNodeExecutionError,
    NodeExecutionResult,
)


class FlowForgeExportExecutor:
    def __init__(
        self,
        *,
        data_movement_repository: FlowForgeDataMovementRepository | None = None,
        artifact_reader: InlineDatasetArtifactReader | None = None,
        local_file_adapter: LocalFileTestExportAdapter | None = None,
        policy_evaluator: ExportPolicyEvaluator | None = None,
    ) -> None:
        self._data_movement_repository = (
            data_movement_repository or FlowForgeDataMovementRepository()
        )
        self._artifact_reader = artifact_reader or InlineDatasetArtifactReader()
        self._local_file_adapter = local_file_adapter or LocalFileTestExportAdapter()
        self._policy_evaluator = policy_evaluator or ExportPolicyEvaluator()

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
            columns = self._artifact_reader.columns(artifact=input_artifact, rows=rows)
            destination = self._resolve_destination(
                workspace_id=workspace_id, config=config
            )
            policy_result = self._policy_evaluator.evaluate(
                artifact=input_artifact, destination=destination, row_count=len(rows)
            )
            if not policy_result.get("allowed"):
                raise FlowForgeNodeExecutionError(
                    f"Export blocked by policy: {policy_result.get('reason')}."
                )
            write_result = self._write_export(
                rows=rows,
                columns=columns,
                destination=destination,
                config=config,
                run_id=run_id,
                node_id=node_id,
            )
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

        artifact_key = str(
            config.get("output_artifact_key") or config.get("artifact_key") or ""
        ).strip()
        if not artifact_key:
            artifact_key = f"run:{int(run_id)}:node:{node_id}:export_payload"
        export_artifact = self._data_movement_repository.create_dataset_artifact(
            workspace_id=workspace_id,
            run_id=run_id,
            node_id=node_id,
            artifact_key=artifact_key,
            artifact_type="export_payload",
            storage_kind=str(
                write_result.destination_ref.get("destination_type")
                or "local_file_test"
            ),
            storage_ref=write_result.destination_ref,
            schema={"columns": columns, "export_policy": policy_result},
            row_count=write_result.row_count,
            byte_count=write_result.byte_count,
            checksum=write_result.checksum,
            status="ready",
            expires_at=None,
            created_by="flowforge",
        )
        self._data_movement_repository.create_data_movement_audit(
            workspace_id=workspace_id,
            run_id=run_id,
            node_id=node_id,
            action_type="export",
            status="completed",
            source_key=f"artifact:{int(input_artifact['id'])}",
            destination_key=str(destination.get("destination_key") or "").strip(),
            dataset_artifact_id=int(export_artifact["id"]),
            resource_set_id=None,
            actor_type="system",
            actor_id="flowforge",
            request={
                "input_artifact_id": int(input_artifact["id"]),
                "destination_key": destination.get("destination_key"),
                "format": write_result.format,
            },
            result={
                "artifact_id": int(export_artifact["id"]),
                "row_count": write_result.row_count,
                "byte_count": write_result.byte_count,
                "checksum": write_result.checksum,
                "destination_ref": write_result.destination_ref,
                "export_policy": policy_result,
            },
            error_message=None,
            idempotency_key=f"{artifact_key}:audit",
            completed_at=None,
        )
        artifact_ref = {
            "artifact_id": int(export_artifact["id"]),
            "artifact_key": artifact_key,
            "artifact_type": "export_payload",
            "node_id": node_id,
            "row_count": write_result.row_count,
            "byte_count": write_result.byte_count,
            "checksum": write_result.checksum,
            "destination": write_result.destination_ref,
        }
        next_node_id = self._first_target(outgoing_edges)
        return NodeExecutionResult(
            status="advance" if next_node_id else "completed",
            next_node_id=next_node_id,
            event_payload={
                "node_type": "export",
                "next_node_id": next_node_id,
                "data_movement": {
                    "node_type": "export",
                    "execution_status": "completed",
                    "input_artifact_id": int(input_artifact["id"]),
                    "artifact": artifact_ref,
                    "destination": write_result.destination_ref,
                    "export_policy": policy_result,
                },
            },
            run_context_update={
                "artifacts": {node_id: artifact_ref},
                "last_artifact": artifact_ref,
            },
        )

    def _write_export(
        self,
        *,
        rows: list[dict[str, Any]],
        columns: list[dict[str, Any]],
        destination: dict[str, Any],
        config: dict[str, Any],
        run_id: int,
        node_id: str,
    ):
        destination_type = str(destination.get("destination_type") or "").strip()
        if destination_type != "local_file_test":
            raise FlowForgeNodeExecutionError(
                "Only local_file_test export destinations are executable in this phase."
            )
        if str(destination.get("mode") or "test").strip() != "test":
            raise FlowForgeNodeExecutionError(
                "local_file_test exports require a test-mode destination."
            )
        return self._local_file_adapter.write(
            rows=rows,
            columns=columns,
            destination=destination,
            config=config,
            run_id=run_id,
            node_id=node_id,
        )

    def _resolve_destination(
        self, *, workspace_id: str, config: dict[str, Any]
    ) -> dict[str, Any]:
        destination_key = str(config.get("destination_key") or "").strip()
        if not destination_key:
            raise FlowForgeNodeExecutionError("export requires destination_key.")
        destination = self._data_movement_repository.get_data_destination_by_key(
            workspace_id=workspace_id,
            destination_key=destination_key,
        )
        if destination is None:
            raise FlowForgeNodeExecutionError(
                f"Export destination '{destination_key}' was not found."
            )
        if not bool(destination.get("enabled")):
            raise FlowForgeNodeExecutionError(
                f"Export destination '{destination_key}' is disabled."
            )
        return destination

    def _resolve_input_artifact(
        self,
        *,
        workspace_id: str,
        config: dict[str, Any],
        run_context: dict[str, Any],
    ) -> dict[str, Any]:
        artifact_id = self._input_artifact_id(config=config, run_context=run_context)
        if artifact_id is None:
            raise FlowForgeNodeExecutionError("export requires an input artifact.")
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
            action_type="export",
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
            idempotency_key=f"run:{int(run_id)}:node:{node_id}:export:audit:failed",
            completed_at=None,
        )

    @staticmethod
    def _node_config(node: dict[str, Any]) -> dict[str, Any]:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        return {**data, **config}

    @staticmethod
    def _first_target(outgoing_edges: list[dict[str, Any]]) -> str | None:
        for edge in sorted(outgoing_edges, key=lambda row: str(row.get("id") or "")):
            target = str(edge.get("target") or "").strip()
            if target:
                return target
        return None
