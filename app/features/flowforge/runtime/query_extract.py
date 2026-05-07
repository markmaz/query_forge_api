from __future__ import annotations

from typing import Any

from app.config import (
    FLOWFORGE_QUERY_EXTRACT_DEFAULT_LIMIT,
    FLOWFORGE_QUERY_EXTRACT_MAX_LIMIT,
)
from app.features.flowforge.repositories import FlowForgeDataMovementRepository
from app.features.flowforge.runtime.artifacts import DatasetArtifactMetadataBuilder
from app.features.flowforge.runtime.node_executor import (
    FlowForgeNodeExecutionError,
    NodeExecutionResult,
)
from app.features.flowforge.runtime.query_extract_sources import (
    QueryExtractResolver,
    QueryForgeSavedQueryExtractResolver,
)

RAW_SQL_KEYS = {"raw_sql", "rawSql", "sql", "query", "sqlRendered", "qf_rendered_sql"}


class FlowForgeQueryExtractExecutor:
    def __init__(
        self,
        *,
        data_movement_repository: FlowForgeDataMovementRepository | None = None,
        resolver: QueryExtractResolver | None = None,
        artifact_metadata_builder: DatasetArtifactMetadataBuilder | None = None,
        default_preview_limit: int | None = None,
        max_preview_limit: int | None = None,
    ) -> None:
        self._data_movement_repository = (
            data_movement_repository or FlowForgeDataMovementRepository()
        )
        self._resolver = resolver or QueryForgeSavedQueryExtractResolver()
        self._artifact_metadata_builder = (
            artifact_metadata_builder or DatasetArtifactMetadataBuilder()
        )
        self._default_preview_limit = max(
            1,
            int(
                FLOWFORGE_QUERY_EXTRACT_DEFAULT_LIMIT
                if default_preview_limit is None
                else default_preview_limit
            ),
        )
        self._max_preview_limit = max(
            0,
            int(
                FLOWFORGE_QUERY_EXTRACT_MAX_LIMIT
                if max_preview_limit is None
                else max_preview_limit
            ),
        )

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
        try:
            self._reject_raw_sql(config=config, node_id=node_id)
            preview_limit = self._preview_limit(config.get("preview_limit"))
            source_result = self._resolver.execute_preview(
                workspace_id=workspace_id,
                node_config=config,
                preview_limit=preview_limit,
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
        metadata = self._artifact_metadata_builder.build_query_extract_metadata(
            rows=source_result.rows,
            columns=source_result.columns,
            source=source_result.source.descriptor,
            preview_limit=preview_limit,
        )
        artifact_key = f"run:{int(run_id)}:node:{node_id}:query_extract"
        artifact = self._data_movement_repository.create_dataset_artifact(
            workspace_id=workspace_id,
            run_id=run_id,
            node_id=node_id,
            artifact_key=artifact_key,
            artifact_type="query_extract",
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
            action_type="query_extract",
            status="completed",
            source_key=source_result.source.source_id,
            destination_key=None,
            dataset_artifact_id=int(artifact["id"]),
            resource_set_id=None,
            actor_type="system",
            actor_id="flowforge",
            request={
                "source_kind": source_result.source.source_kind,
                "source_id": source_result.source.source_id,
                "preview_limit": preview_limit,
            },
            result={
                "row_count": metadata["row_count"],
                "checksum": metadata["checksum"],
                "artifact_id": int(artifact["id"]),
            },
            error_message=None,
            idempotency_key=f"{artifact_key}:audit",
            completed_at=None,
        )
        artifact_ref = {
            "artifact_id": int(artifact["id"]),
            "artifact_key": artifact_key,
            "artifact_type": "query_extract",
            "node_id": node_id,
            "row_count": metadata["row_count"],
            "checksum": metadata["checksum"],
            "source": source_result.source.descriptor,
        }
        next_node_id = self._first_target(outgoing_edges)
        return NodeExecutionResult(
            status="advance" if next_node_id else "completed",
            next_node_id=next_node_id,
            event_payload={
                "node_type": "query_extract",
                "next_node_id": next_node_id,
                "data_movement": {
                    "node_type": "query_extract",
                    "execution_status": "completed",
                    "artifact": artifact_ref,
                    "source": source_result.source.descriptor,
                },
            },
            run_context_update={
                "artifacts": {node_id: artifact_ref},
                "last_artifact": artifact_ref,
            },
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
        config = self._node_config(node)
        self._data_movement_repository.create_data_movement_audit(
            workspace_id=workspace_id,
            run_id=run_id,
            node_id=node_id,
            action_type="query_extract",
            status="failed",
            source_key=str(
                config.get("saved_query_id") or config.get("semantic_plan_id") or ""
            ).strip()
            or None,
            destination_key=None,
            dataset_artifact_id=None,
            resource_set_id=None,
            actor_type="system",
            actor_id="flowforge",
            request={"node_id": node_id},
            result=None,
            error_message=error_message,
            idempotency_key=f"run:{int(run_id)}:node:{node_id}:query_extract:audit:failed",
            completed_at=None,
        )

    @staticmethod
    def _node_config(node: dict[str, Any]) -> dict[str, Any]:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        config = node.get("config") if isinstance(node.get("config"), dict) else {}
        return {**data, **config}

    def _preview_limit(self, value: Any) -> int:
        raw_limit = self._default_preview_limit if value in (None, "") else value
        if isinstance(raw_limit, str) and raw_limit.strip().lower() in {
            "max",
            "maximum",
        }:
            if self._max_preview_limit <= 0:
                raise FlowForgeNodeExecutionError(
                    "query_extract preview_limit=max requires FLOWFORGE_QUERY_EXTRACT_MAX_LIMIT to be configured."
                )
            return self._max_preview_limit
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise FlowForgeNodeExecutionError(
                "query_extract preview_limit must be an integer."
            ) from None
        if limit < 1:
            raise FlowForgeNodeExecutionError(
                "query_extract preview_limit must be positive."
            )
        if self._max_preview_limit > 0:
            return min(limit, self._max_preview_limit)
        return limit

    @staticmethod
    def _reject_raw_sql(*, config: dict[str, Any], node_id: str) -> None:
        present = sorted(key for key in RAW_SQL_KEYS if key in config)
        if present:
            raise FlowForgeNodeExecutionError(
                f"Query extract node '{node_id}' cannot define raw SQL fields: {', '.join(present)}."
            )

    @staticmethod
    def _first_target(outgoing_edges: list[dict[str, Any]]) -> str | None:
        for edge in sorted(outgoing_edges, key=lambda row: str(row.get("id") or "")):
            target = str(edge.get("target") or "").strip()
            if target:
                return target
        return None
