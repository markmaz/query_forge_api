from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any


class DatasetArtifactMetadataBuilder:
    def build_query_extract_metadata(
        self,
        *,
        rows: list[dict[str, Any]],
        columns: list[dict[str, Any]],
        source: dict[str, Any],
        preview_limit: int,
    ) -> dict[str, Any]:
        normalized_rows = self._json_safe(rows)
        normalized_columns = self._json_safe(columns)
        return {
            "row_count": len(normalized_rows),
            "checksum": self._checksum(
                {"columns": normalized_columns, "rows": normalized_rows}
            ),
            "schema": {
                "columns": normalized_columns,
                "sensitivity": self._sensitivity_metadata(normalized_columns),
            },
            "storage_ref": {
                "storage_kind": "preview_metadata",
                "source": source,
                "preview_limit": int(preview_limit),
                "preview_row_count": len(normalized_rows),
                "columns": normalized_columns,
                "rows": normalized_rows,
            },
        }

    def build_transform_metadata(
        self,
        *,
        rows: list[dict[str, Any]],
        columns: list[dict[str, Any]],
        input_artifact: dict[str, Any],
        validation_summary: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_rows = self._json_safe(rows)
        normalized_columns = self._json_safe(columns)
        normalized_validation = self._json_safe(validation_summary)
        return {
            "row_count": len(normalized_rows),
            "checksum": self._checksum(
                {"columns": normalized_columns, "rows": normalized_rows}
            ),
            "schema": {
                "columns": normalized_columns,
                "sensitivity": self._sensitivity_metadata(normalized_columns),
                "validation": normalized_validation,
            },
            "storage_ref": {
                "storage_kind": "preview_metadata",
                "input_artifact": self._artifact_descriptor(input_artifact),
                "validation_summary": normalized_validation,
                "columns": normalized_columns,
                "rows": normalized_rows,
            },
        }

    def build_import_metadata(
        self,
        *,
        rows: list[dict[str, Any]],
        columns: list[dict[str, Any]],
        source_ref: dict[str, Any],
        validation_summary: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_rows = self._json_safe(rows)
        normalized_columns = self._json_safe(columns)
        normalized_validation = self._json_safe(validation_summary)
        return {
            "row_count": len(normalized_rows),
            "checksum": self._checksum(
                {"columns": normalized_columns, "rows": normalized_rows}
            ),
            "schema": {
                "columns": normalized_columns,
                "sensitivity": self._sensitivity_metadata(normalized_columns),
                "validation": normalized_validation,
            },
            "storage_ref": {
                "storage_kind": "preview_metadata",
                "source": self._json_safe(source_ref),
                "validation_summary": normalized_validation,
                "columns": normalized_columns,
                "rows": normalized_rows,
            },
        }

    def _artifact_descriptor(self, artifact: dict[str, Any]) -> dict[str, Any]:
        return {
            "artifact_id": artifact.get("id"),
            "artifact_key": artifact.get("artifact_key"),
            "artifact_type": artifact.get("artifact_type"),
            "row_count": artifact.get("row_count"),
            "checksum": artifact.get("checksum"),
        }

    def _sensitivity_metadata(self, columns: list[dict[str, Any]]) -> dict[str, Any]:
        sensitive_columns = []
        for column in columns:
            key = str(
                column.get("key") or column.get("name") or column.get("label") or ""
            ).lower()
            if any(
                token in key
                for token in (
                    "email",
                    "phone",
                    "ssn",
                    "dob",
                    "birth",
                    "patient",
                    "member",
                )
            ):
                sensitive_columns.append(
                    column.get("key") or column.get("name") or column.get("label")
                )
        return {
            "classification": "possible_sensitive"
            if sensitive_columns
            else "unclassified",
            "sensitive_columns": [value for value in sensitive_columns if value],
        }

    def _checksum(self, payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            self._json_safe(payload), sort_keys=True, separators=(",", ":"), default=str
        )
        return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _json_safe(self, value: Any) -> Any:
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, dict):
            return {str(key): self._json_safe(child) for key, child in value.items()}
        if isinstance(value, list):
            return [self._json_safe(child) for child in value]
        return value
