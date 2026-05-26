from __future__ import annotations

from typing import Any

from app.features.flowforge.repositories import FlowForgeDataMovementRepository, FlowForgeResourceRepository
from app.features.flowforge.runtime.artifacts import DatasetArtifactMetadataBuilder
from app.features.flowforge.runtime.import_sources import LocalFileTestImportAdapter
from app.features.flowforge.runtime.node_executor import FlowForgeNodeExecutionError, NodeExecutionResult
from app.features.flowforge.runtime.resource_import import ResourceSetActivationService


class FlowForgeImportExecutor:
    def __init__(
        self,
        *,
        data_movement_repository: FlowForgeDataMovementRepository | None = None,
        resource_repository: FlowForgeResourceRepository | None = None,
        local_file_adapter: LocalFileTestImportAdapter | None = None,
        artifact_metadata_builder: DatasetArtifactMetadataBuilder | None = None,
        resource_activation_service: ResourceSetActivationService | None = None,
    ) -> None:
        self._data_movement_repository = data_movement_repository or FlowForgeDataMovementRepository()
        self._resource_activation_service = resource_activation_service or ResourceSetActivationService(
            resource_repository=resource_repository,
        )
        self._local_file_adapter = local_file_adapter or LocalFileTestImportAdapter()
        self._artifact_metadata_builder = artifact_metadata_builder or DatasetArtifactMetadataBuilder()

    def execute(
        self,
        *,
        workspace_id: str,
        run_id: int,
        node: dict[str, Any],
        outgoing_edges: list[dict[str, Any]],
        run_context: dict[str, Any],
    ) -> NodeExecutionResult:
        del run_context
        node_id = str(node.get("id") or "").strip()
        config = self._node_config(node)
        artifact = None
        activation = None
        audited_failure = False
        source_key = str(config.get("source_key") or "").strip() or None
        resource_set_id = self._optional_int(config.get("resource_set_id"))
        try:
            source = self._resolve_source(workspace_id=workspace_id, config=config)
            imported = self._local_file_adapter.read(source=source, config=config)
            validation = (
                self._resource_activation_service.validate(rows=imported.rows)
                if resource_set_id is not None
                else None
            )
            validation_summary = validation.summary if validation is not None else {
                "input_row_count": len(imported.rows),
                "valid_row_count": len(imported.rows),
                "invalid_row_count": 0,
                "invalid_rows": [],
            }
            metadata = self._artifact_metadata_builder.build_import_metadata(
                rows=imported.rows,
                columns=imported.columns,
                source_ref=imported.source_ref,
                validation_summary=validation_summary,
            )
            artifact_key = str(config.get("artifact_key") or config.get("output_artifact_key") or "").strip()
            if not artifact_key:
                artifact_key = f"run:{int(run_id)}:node:{node_id}:import"
            has_invalid_rows = int(validation_summary.get("invalid_row_count") or 0) > 0
            artifact = self._data_movement_repository.create_dataset_artifact(
                workspace_id=workspace_id,
                run_id=run_id,
                node_id=node_id,
                artifact_key=artifact_key,
                artifact_type="import",
                storage_kind="preview_metadata",
                storage_ref=metadata["storage_ref"],
                schema=metadata["schema"],
                row_count=metadata["row_count"],
                byte_count=imported.byte_count,
                checksum=metadata["checksum"],
                status="validation_failed" if has_invalid_rows else "staged",
                expires_at=None,
                created_by="flowforge",
            )
            if has_invalid_rows:
                self._record_audit(
                    workspace_id=workspace_id,
                    run_id=run_id,
                    node_id=node_id,
                    source_key=str(source.get("source_key") or "").strip(),
                    resource_set_id=resource_set_id,
                    artifact_id=int(artifact["id"]),
                    status="failed",
                    request={"source_key": source.get("source_key"), "filename": config.get("filename")},
                    result={"artifact_id": int(artifact["id"]), "validation": validation_summary},
                    error_message="Import contains invalid rows.",
                    idempotency_key=f"{artifact_key}:audit:validation_failed",
                )
                audited_failure = True
                raise FlowForgeNodeExecutionError("Import contains invalid rows; resource activation was skipped.")
            if bool(config.get("activate")):
                if resource_set_id is None:
                    raise FlowForgeNodeExecutionError("import activate=true requires resource_set_id.")
                activation = self._resource_activation_service.activate(
                    workspace_id=workspace_id,
                    resource_set_id=resource_set_id,
                    rows=imported.rows,
                    mode=str(source.get("mode") or "test").strip(),
                    source_ref=imported.source_ref,
                    actor_id="flowforge",
                )
            self._record_audit(
                workspace_id=workspace_id,
                run_id=run_id,
                node_id=node_id,
                source_key=str(source.get("source_key") or "").strip(),
                resource_set_id=resource_set_id,
                artifact_id=int(artifact["id"]),
                status="completed",
                request={"source_key": source.get("source_key"), "filename": config.get("filename"), "activate": bool(config.get("activate"))},
                result={"artifact_id": int(artifact["id"]), "validation": validation_summary, "activation": activation},
                error_message=None,
                idempotency_key=f"{artifact_key}:audit",
            )
        except FlowForgeNodeExecutionError as exc:
            if artifact is None:
                self._record_failed_audit_safely(
                    workspace_id=workspace_id,
                    run_id=run_id,
                    node=node,
                    error_message=str(exc),
                )
            elif not audited_failure:
                self._record_audit(
                    workspace_id=workspace_id,
                    run_id=run_id,
                    node_id=node_id,
                    source_key=source_key,
                    resource_set_id=resource_set_id,
                    artifact_id=int(artifact["id"]),
                    status="failed",
                    request={"node_id": node_id, "activate": bool(config.get("activate"))},
                    result={"artifact_id": int(artifact["id"])},
                    error_message=str(exc),
                    idempotency_key=f"{artifact['artifact_key']}:audit:failed",
                )
            raise
        except Exception as exc:
            if artifact is None:
                self._record_failed_audit_safely(
                    workspace_id=workspace_id,
                    run_id=run_id,
                    node=node,
                    error_message=str(exc),
                )
            raise FlowForgeNodeExecutionError(str(exc)) from exc

        artifact_ref = {
            "artifact_id": int(artifact["id"]),
            "artifact_key": str(artifact["artifact_key"]),
            "artifact_type": "import",
            "node_id": node_id,
            "row_count": artifact.get("row_count"),
            "checksum": artifact.get("checksum"),
            "status": artifact.get("status"),
        }
        next_node_id = self._first_target(outgoing_edges)
        return NodeExecutionResult(
            status="advance" if next_node_id else "completed",
            next_node_id=next_node_id,
            event_payload={
                "node_type": "import",
                "next_node_id": next_node_id,
                "data_movement": {
                    "node_type": "import",
                    "execution_status": "completed",
                    "artifact": artifact_ref,
                    "activation": activation,
                },
            },
            run_context_update={
                "artifacts": {node_id: artifact_ref},
                "last_artifact": artifact_ref,
            },
        )

    def _resolve_source(self, *, workspace_id: str, config: dict[str, Any]) -> dict[str, Any]:
        source_key = str(config.get("source_key") or "").strip()
        if not source_key:
            raise FlowForgeNodeExecutionError("import requires source_key.")
        source = self._data_movement_repository.get_data_source_by_key(
            workspace_id=workspace_id,
            source_key=source_key,
        )
        if source is None:
            raise FlowForgeNodeExecutionError(f"Import source '{source_key}' was not found.")
        if not bool(source.get("enabled")):
            raise FlowForgeNodeExecutionError(f"Import source '{source_key}' is disabled.")
        return source

    def _record_audit(
        self,
        *,
        workspace_id: str,
        run_id: int,
        node_id: str,
        source_key: str | None,
        resource_set_id: int | None,
        artifact_id: int | None,
        status: str,
        request: dict[str, Any],
        result: dict[str, Any] | None,
        error_message: str | None,
        idempotency_key: str,
    ) -> None:
        self._data_movement_repository.create_data_movement_audit(
            workspace_id=workspace_id,
            run_id=run_id,
            node_id=node_id,
            action_type="import",
            status=status,
            source_key=source_key,
            destination_key=None,
            dataset_artifact_id=artifact_id,
            resource_set_id=resource_set_id,
            actor_type="system",
            actor_id="flowforge",
            request=request,
            result=result,
            error_message=error_message,
            idempotency_key=idempotency_key,
            completed_at=None,
        )

    def _record_failed_audit_safely(
        self,
        *,
        workspace_id: str,
        run_id: int,
        node: dict[str, Any],
        error_message: str,
    ) -> None:
        try:
            node_id = str(node.get("id") or "").strip()
            config = self._node_config(node)
            self._record_audit(
                workspace_id=workspace_id,
                run_id=run_id,
                node_id=node_id,
                source_key=str(config.get("source_key") or "").strip() or None,
                resource_set_id=self._optional_int(config.get("resource_set_id")),
                artifact_id=None,
                status="failed",
                request={"node_id": node_id},
                result=None,
                error_message=error_message,
                idempotency_key=f"run:{int(run_id)}:node:{node_id}:import:audit:failed",
            )
        except Exception:
            return

    @staticmethod
    def _node_config(node: dict[str, Any]) -> dict[str, Any]:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        return {**data, **config}

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        return int(value)

    @staticmethod
    def _first_target(outgoing_edges: list[dict[str, Any]]) -> str | None:
        for edge in sorted(outgoing_edges, key=lambda row: str(row.get("id") or "")):
            target = str(edge.get("target") or "").strip()
            if target:
                return target
        return None
