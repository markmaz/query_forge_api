from __future__ import annotations

from typing import Any

from app.exceptions.forge_error import ForgeError
from app.features.flowforge.service.data_movement_serializers import FlowForgeDataMovementSerializerMixin
from app.features.flowforge.service.data_movement_validation import FlowForgeDataMovementValidationMixin


class FlowForgeDataMovementServiceMixin(
    FlowForgeDataMovementValidationMixin,
    FlowForgeDataMovementSerializerMixin,
):
    def create_dataset_artifact(
        self,
        *,
        workspace_id: str,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ForgeError("dataset artifact payload must be an object.", status_code=400)
        artifact_key = str(payload.get("artifact_key") or "").strip()
        artifact_type = str(payload.get("artifact_type") or "").strip()
        if not artifact_key:
            raise ForgeError("artifact_key is required.", status_code=400)
        if not artifact_type:
            raise ForgeError("artifact_type is required.", status_code=400)
        status = str(payload.get("status") or "ready").strip()
        if status not in self._ARTIFACT_STATUSES:
            options = ", ".join(sorted(self._ARTIFACT_STATUSES))
            raise ForgeError(f"status must be one of {options}.", status_code=400)
        row = self._data_movement_repository.create_dataset_artifact(
            workspace_id=workspace_id,
            run_id=self._optional_positive_int(payload.get("run_id"), field_name="run_id"),
            node_id=self._optional_string(payload.get("node_id")),
            artifact_key=artifact_key,
            artifact_type=artifact_type,
            storage_kind=str(payload.get("storage_kind") or "metadata_only").strip(),
            storage_ref=payload.get("storage_ref") if isinstance(payload.get("storage_ref"), dict) else None,
            schema=payload.get("schema") if isinstance(payload.get("schema"), (dict, list)) else None,
            row_count=self._optional_non_negative_int(payload.get("row_count"), field_name="row_count"),
            byte_count=self._optional_non_negative_int(payload.get("byte_count"), field_name="byte_count"),
            checksum=self._optional_string(payload.get("checksum")),
            status=status,
            expires_at=payload.get("expires_at"),
            created_by=str(actor_user_id or "").strip() or None,
        )
        return self._serialize_dataset_artifact(row)

    def list_dataset_artifacts(
        self,
        *,
        workspace_id: str,
        run_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        safe_limit = min(max(int(limit or 100), 1), 500)
        safe_offset = max(int(offset or 0), 0)
        safe_run_id = self._optional_positive_int(run_id, field_name="run_id")
        rows = self._data_movement_repository.list_dataset_artifacts(
            workspace_id=workspace_id,
            run_id=safe_run_id,
            limit=safe_limit,
            offset=safe_offset,
        )
        return {
            "run_id": safe_run_id,
            "limit": safe_limit,
            "offset": safe_offset,
            "artifacts": [self._serialize_dataset_artifact(row) for row in rows],
        }

    def get_dataset_artifact(self, *, workspace_id: str, artifact_id: int) -> dict[str, Any]:
        artifact = self._data_movement_repository.get_dataset_artifact(
            workspace_id=workspace_id,
            artifact_id=self._positive_int(artifact_id, field_name="artifact_id"),
        )
        if artifact is None:
            raise ForgeError(f"Dataset artifact '{artifact_id}' was not found.", status_code=404)
        return self._serialize_dataset_artifact(artifact)

    def record_data_movement_audit(
        self,
        *,
        workspace_id: str,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ForgeError("audit payload must be an object.", status_code=400)
        action_type = str(payload.get("action_type") or "").strip()
        if action_type not in self._AUDIT_ACTION_TYPES:
            raise ForgeError("action_type must be one of query_extract, export, import, map_transform, or approval.", status_code=400)
        status = str(payload.get("status") or "started").strip()
        if status not in self._AUDIT_STATUSES:
            raise ForgeError("status must be one of started, completed, failed, or canceled.", status_code=400)
        row = self._data_movement_repository.create_data_movement_audit(
            workspace_id=workspace_id,
            run_id=self._optional_positive_int(payload.get("run_id"), field_name="run_id"),
            node_id=self._optional_string(payload.get("node_id")),
            action_type=action_type,
            status=status,
            source_key=self._optional_string(payload.get("source_key")),
            destination_key=self._optional_string(payload.get("destination_key")),
            dataset_artifact_id=self._optional_positive_int(payload.get("dataset_artifact_id"), field_name="dataset_artifact_id"),
            resource_set_id=self._optional_positive_int(payload.get("resource_set_id"), field_name="resource_set_id"),
            actor_type=self._optional_string(payload.get("actor_type")) or "user",
            actor_id=self._optional_string(payload.get("actor_id")) or str(actor_user_id or "").strip() or None,
            request=payload.get("request") if isinstance(payload.get("request"), dict) else None,
            result=payload.get("result") if isinstance(payload.get("result"), dict) else None,
            error_message=self._optional_string(payload.get("error_message")),
            idempotency_key=self._optional_string(payload.get("idempotency_key")),
            completed_at=payload.get("completed_at"),
        )
        return self._serialize_data_movement_audit(row)

    def list_data_movement_audit(
        self,
        *,
        workspace_id: str,
        run_id: int | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        safe_limit = min(max(int(limit or 100), 1), 500)
        safe_offset = max(int(offset or 0), 0)
        safe_run_id = self._optional_positive_int(run_id, field_name="run_id")
        rows = self._data_movement_repository.list_data_movement_audit(
            workspace_id=workspace_id,
            run_id=safe_run_id,
            limit=safe_limit,
            offset=safe_offset,
        )
        return {
            "run_id": safe_run_id,
            "limit": safe_limit,
            "offset": safe_offset,
            "audit": [self._serialize_data_movement_audit(row) for row in rows],
        }

    def upsert_data_source(self, *, workspace_id: str, payload: dict[str, Any], actor_user_id: str) -> dict[str, Any]:
        source_key = self._require_data_movement_key(
            payload.get("source_key") if isinstance(payload, dict) else None,
            field_name="source_key",
        )
        display_name = str(payload.get("display_name") or "").strip() if isinstance(payload, dict) else ""
        if not display_name:
            raise ForgeError("display_name is required.", status_code=400)
        source_type = self._require_allowlist_type(payload=payload, field_name="source_type", allowed=self._SOURCE_TYPES)
        mode = self._require_allowlist_mode(payload.get("mode") if isinstance(payload, dict) else None)
        row = self._data_movement_repository.upsert_data_source(
            workspace_id=workspace_id,
            source_key=source_key,
            display_name=display_name,
            source_type=source_type,
            enabled=bool(payload.get("enabled", True)),
            mode=mode,
            config=payload.get("config") if isinstance(payload.get("config"), dict) else {},
            actor_user_id=str(actor_user_id or "").strip() or None,
        )
        return self._serialize_data_source(row)

    def list_data_sources(self, *, workspace_id: str) -> list[dict[str, Any]]:
        return [self._serialize_data_source(row) for row in self._data_movement_repository.list_data_sources(workspace_id=workspace_id)]

    def test_data_source(self, *, workspace_id: str, source_key: str) -> dict[str, Any]:
        normalized_key = str(source_key or "").strip()
        if not normalized_key:
            raise ForgeError("source_key is required.", status_code=400)
        row = self._data_movement_repository.get_data_source_by_key(workspace_id=workspace_id, source_key=normalized_key)
        if row is None:
            raise ForgeError(f"Data source '{normalized_key}' was not found.", status_code=404)
        return self._data_movement_test_result(row=row, kind="source")

    def set_data_source_enabled(self, *, workspace_id: str, source_key: str, enabled: bool, actor_user_id: str) -> dict[str, Any]:
        normalized_key = str(source_key or "").strip()
        if not normalized_key:
            raise ForgeError("source_key is required.", status_code=400)
        updated = self._data_movement_repository.update_data_source_enabled(
            workspace_id=workspace_id,
            source_key=normalized_key,
            enabled=bool(enabled),
            updated_by=str(actor_user_id or "").strip() or None,
        )
        if not updated:
            raise ForgeError(f"Data source '{normalized_key}' was not found.", status_code=404)
        row = self._data_movement_repository.get_data_source_by_key(workspace_id=workspace_id, source_key=normalized_key)
        return self._serialize_data_source(row or {"source_key": normalized_key, "enabled": bool(enabled)})

    def upsert_data_destination(self, *, workspace_id: str, payload: dict[str, Any], actor_user_id: str) -> dict[str, Any]:
        destination_key = self._require_data_movement_key(
            payload.get("destination_key") if isinstance(payload, dict) else None,
            field_name="destination_key",
        )
        display_name = str(payload.get("display_name") or "").strip() if isinstance(payload, dict) else ""
        if not display_name:
            raise ForgeError("display_name is required.", status_code=400)
        destination_type = self._require_allowlist_type(
            payload=payload,
            field_name="destination_type",
            allowed=self._DESTINATION_TYPES,
        )
        mode = self._require_allowlist_mode(payload.get("mode") if isinstance(payload, dict) else None)
        row = self._data_movement_repository.upsert_data_destination(
            workspace_id=workspace_id,
            destination_key=destination_key,
            display_name=display_name,
            destination_type=destination_type,
            enabled=bool(payload.get("enabled", True)),
            mode=mode,
            config=payload.get("config") if isinstance(payload.get("config"), dict) else {},
            actor_user_id=str(actor_user_id or "").strip() or None,
        )
        return self._serialize_data_destination(row)

    def list_data_destinations(self, *, workspace_id: str) -> list[dict[str, Any]]:
        return [
            self._serialize_data_destination(row)
            for row in self._data_movement_repository.list_data_destinations(workspace_id=workspace_id)
        ]

    def test_data_destination(self, *, workspace_id: str, destination_key: str) -> dict[str, Any]:
        normalized_key = str(destination_key or "").strip()
        if not normalized_key:
            raise ForgeError("destination_key is required.", status_code=400)
        row = self._data_movement_repository.get_data_destination_by_key(
            workspace_id=workspace_id,
            destination_key=normalized_key,
        )
        if row is None:
            raise ForgeError(f"Data destination '{normalized_key}' was not found.", status_code=404)
        return self._data_movement_test_result(row=row, kind="destination")

    def set_data_destination_enabled(
        self,
        *,
        workspace_id: str,
        destination_key: str,
        enabled: bool,
        actor_user_id: str,
    ) -> dict[str, Any]:
        normalized_key = str(destination_key or "").strip()
        if not normalized_key:
            raise ForgeError("destination_key is required.", status_code=400)
        updated = self._data_movement_repository.update_data_destination_enabled(
            workspace_id=workspace_id,
            destination_key=normalized_key,
            enabled=bool(enabled),
            updated_by=str(actor_user_id or "").strip() or None,
        )
        if not updated:
            raise ForgeError(f"Data destination '{normalized_key}' was not found.", status_code=404)
        row = self._data_movement_repository.get_data_destination_by_key(workspace_id=workspace_id, destination_key=normalized_key)
        return self._serialize_data_destination(row or {"destination_key": normalized_key, "enabled": bool(enabled)})

    def _data_movement_test_result(self, *, row: dict[str, Any], kind: str) -> dict[str, Any]:
        key_field = f"{kind}_key"
        type_field = f"{kind}_type"
        key = str(row.get(key_field) or "").strip()
        connection_type = str(row.get(type_field) or "").strip()
        enabled = bool(row.get("enabled"))
        mode = str(row.get("mode") or "test").strip()
        config = row.get("config_json") or row.get("config") or {}
        has_config = isinstance(config, dict) and bool(config)
        return {
            "ok": enabled and has_config,
            "key": key,
            "kind": kind,
            "type": connection_type,
            "mode": mode,
            "enabled": enabled,
            "message": (
                f"{kind.title()} '{key}' is enabled and has testable configuration."
                if enabled and has_config
                else f"{kind.title()} '{key}' needs enabled state and configuration before runtime use."
            ),
        }
