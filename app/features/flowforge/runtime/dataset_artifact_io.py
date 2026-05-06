from __future__ import annotations

from typing import Any

from app.features.flowforge.runtime.node_executor import FlowForgeNodeExecutionError


class InlineDatasetArtifactReader:
    def rows(self, artifact: dict[str, Any]) -> list[dict[str, Any]]:
        storage_ref = self._storage_ref(artifact)
        rows = storage_ref.get("rows") or storage_ref.get("preview_rows")
        if not isinstance(rows, list):
            raise FlowForgeNodeExecutionError(
                f"Input artifact '{artifact.get('id')}' does not contain inline preview rows."
            )
        return [row for row in rows if isinstance(row, dict)]

    def columns(
        self,
        *,
        artifact: dict[str, Any],
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        storage_ref = self._storage_ref(artifact)
        columns = storage_ref.get("columns")
        if isinstance(columns, list):
            normalized = [column for column in columns if isinstance(column, dict)]
            if normalized:
                return normalized
        schema = artifact.get("schema_json") or artifact.get("schema") or {}
        if isinstance(schema, dict) and isinstance(schema.get("columns"), list):
            normalized = [
                column for column in schema["columns"] if isinstance(column, dict)
            ]
            if normalized:
                return normalized
        return [
            {"key": key, "label": key.replace("_", " ").title()}
            for key in self._row_keys(rows)
        ]

    def _storage_ref(self, artifact: dict[str, Any]) -> dict[str, Any]:
        storage_ref = (
            artifact.get("storage_ref_json") or artifact.get("storage_ref") or {}
        )
        return storage_ref if isinstance(storage_ref, dict) else {}

    def _row_keys(self, rows: list[dict[str, Any]]) -> list[str]:
        keys: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    keys.append(key)
        return keys
