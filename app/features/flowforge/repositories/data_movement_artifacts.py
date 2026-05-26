from __future__ import annotations

from datetime import datetime
from typing import Any

from app.features.flowforge.repositories.common import json_or_none as _json_or_none, lastrowid as _lastrowid


class FlowForgeDataMovementArtifactRepositoryMixin:
    def create_dataset_artifact(
        self,
        *,
        workspace_id: str,
        run_id: int | None,
        node_id: str | None,
        artifact_key: str,
        artifact_type: str,
        storage_kind: str,
        storage_ref: dict[str, Any] | None,
        schema: dict[str, Any] | list[Any] | None,
        row_count: int | None,
        byte_count: int | None,
        checksum: str | None,
        status: str,
        expires_at: datetime | str | None,
        created_by: str | None,
    ) -> dict[str, Any]:
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_dataset_artifacts (
              workspace_id,
              run_id,
              node_id,
              artifact_key,
              artifact_type,
              storage_kind,
              storage_ref_json,
              schema_json,
              row_count,
              byte_count,
              checksum,
              status,
              expires_at,
              created_by
            ) VALUES (
              :workspace_id,
              :run_id,
              :node_id,
              :artifact_key,
              :artifact_type,
              :storage_kind,
              :storage_ref_json,
              :schema_json,
              :row_count,
              :byte_count,
              :checksum,
              :status,
              :expires_at,
              :created_by
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "run_id": int(run_id) if run_id is not None else None,
                "node_id": str(node_id or "").strip() or None,
                "artifact_key": str(artifact_key or "").strip(),
                "artifact_type": str(artifact_type or "").strip(),
                "storage_kind": str(storage_kind or "metadata_only").strip(),
                "storage_ref_json": _json_or_none(storage_ref),
                "schema_json": _json_or_none(schema),
                "row_count": int(row_count) if row_count is not None else None,
                "byte_count": int(byte_count) if byte_count is not None else None,
                "checksum": str(checksum or "").strip() or None,
                "status": str(status or "ready").strip(),
                "expires_at": expires_at,
                "created_by": created_by,
            },
        )
        return {
            "id": _lastrowid(result),
            "workspace_id": str(workspace_id or "").strip(),
            "run_id": int(run_id) if run_id is not None else None,
            "node_id": str(node_id or "").strip() or None,
            "artifact_key": str(artifact_key or "").strip(),
            "artifact_type": str(artifact_type or "").strip(),
            "storage_kind": str(storage_kind or "metadata_only").strip(),
            "storage_ref_json": storage_ref or {},
            "schema_json": schema or {},
            "row_count": int(row_count) if row_count is not None else None,
            "byte_count": int(byte_count) if byte_count is not None else None,
            "checksum": str(checksum or "").strip() or None,
            "status": str(status or "ready").strip(),
            "expires_at": expires_at,
        }

    def list_dataset_artifacts(
        self,
        *,
        workspace_id: str,
        run_id: int | None = None,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        run_filter = "AND run_id = :run_id" if run_id is not None else ""
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT *
            FROM flowforge_dataset_artifacts
            WHERE workspace_id = :workspace_id
              {run_filter}
            ORDER BY created_at DESC, id DESC
            LIMIT :limit OFFSET :offset
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "run_id": int(run_id) if run_id is not None else None,
                "limit": int(limit),
                "offset": int(offset),
            },
        )
        return [self._decode_dataset_artifact(row) for row in rows]

    def get_dataset_artifact(self, *, workspace_id: str, artifact_id: int) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_dataset_artifacts
            WHERE workspace_id = :workspace_id
              AND id = :artifact_id
            LIMIT 1
            """,
            {"workspace_id": str(workspace_id or "").strip(), "artifact_id": int(artifact_id)},
        )
        if not rows:
            return None
        return self._decode_dataset_artifact(rows[0])
