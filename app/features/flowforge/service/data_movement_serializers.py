from __future__ import annotations

from typing import Any


class FlowForgeDataMovementSerializerMixin:
    _SECRET_KEYS = {"password", "secret", "token", "api_key", "apikey", "access_key", "secret_key", "private_key"}

    def _serialize_dataset_artifact(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(row["id"]) if row.get("id") is not None else None,
            "workspace_id": row.get("workspace_id"),
            "run_id": int(row["run_id"]) if row.get("run_id") is not None else None,
            "node_id": row.get("node_id"),
            "artifact_key": row.get("artifact_key"),
            "artifact_type": row.get("artifact_type"),
            "storage_kind": row.get("storage_kind") or "metadata_only",
            "storage_ref": row.get("storage_ref_json") or row.get("storage_ref") or {},
            "schema": row.get("schema_json") or row.get("schema") or {},
            "row_count": int(row["row_count"]) if row.get("row_count") is not None else None,
            "byte_count": int(row["byte_count"]) if row.get("byte_count") is not None else None,
            "checksum": row.get("checksum"),
            "status": row.get("status") or "ready",
            "expires_at": row.get("expires_at"),
            "created_at": row.get("created_at"),
        }

    def _serialize_data_movement_audit(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(row["id"]) if row.get("id") is not None else None,
            "workspace_id": row.get("workspace_id"),
            "run_id": int(row["run_id"]) if row.get("run_id") is not None else None,
            "node_id": row.get("node_id"),
            "action_type": row.get("action_type"),
            "status": row.get("status"),
            "source_key": row.get("source_key"),
            "destination_key": row.get("destination_key"),
            "dataset_artifact_id": int(row["dataset_artifact_id"]) if row.get("dataset_artifact_id") is not None else None,
            "resource_set_id": int(row["resource_set_id"]) if row.get("resource_set_id") is not None else None,
            "actor_type": row.get("actor_type"),
            "actor_id": row.get("actor_id"),
            "request": row.get("request_json") or row.get("request") or {},
            "result": row.get("result_json") or row.get("result") or {},
            "error_message": row.get("error_message"),
            "idempotency_key": row.get("idempotency_key"),
            "started_at": row.get("started_at"),
            "completed_at": row.get("completed_at"),
        }

    def _serialize_data_source(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(row["id"]) if row.get("id") is not None else None,
            "workspace_id": row.get("workspace_id"),
            "source_key": row.get("source_key"),
            "display_name": row.get("display_name"),
            "source_type": row.get("source_type"),
            "enabled": bool(row.get("enabled", False)),
            "mode": row.get("mode") or "test",
            "config": self._redact_config(row.get("config_json") or row.get("config") or {}),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    def _serialize_data_destination(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(row["id"]) if row.get("id") is not None else None,
            "workspace_id": row.get("workspace_id"),
            "destination_key": row.get("destination_key"),
            "display_name": row.get("display_name"),
            "destination_type": row.get("destination_type"),
            "enabled": bool(row.get("enabled", False)),
            "mode": row.get("mode") or "test",
            "config": self._redact_config(row.get("config_json") or row.get("config") or {}),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        }

    def _redact_config(self, value: Any) -> Any:
        if isinstance(value, dict):
            redacted: dict[str, Any] = {}
            for key, child in value.items():
                normalized = str(key).lower().replace("-", "_")
                if normalized in self._SECRET_KEYS or any(secret in normalized for secret in ("password", "secret", "token")):
                    redacted[key] = "********"
                else:
                    redacted[key] = self._redact_config(child)
            return redacted
        if isinstance(value, list):
            return [self._redact_config(item) for item in value]
        return value
