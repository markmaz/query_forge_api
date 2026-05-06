from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.exceptions.forge_error import ForgeError


class FlowForgeResourceServiceMixin:
    def list_resource_sets(self, *, workspace_id: str) -> list[dict[str, Any]]:
        return [self._serialize_resource_set(row) for row in self._resource_repository.list_resource_sets(workspace_id=workspace_id)]

    def create_resource_set(
        self,
        *,
        workspace_id: str,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        resource_set_key = str(payload.get("resource_set_key") or "").strip()
        display_name = str(payload.get("display_name") or "").strip()
        if not resource_set_key:
            raise ForgeError("resource_set_key is required.", status_code=400)
        if not display_name:
            raise ForgeError("display_name is required.", status_code=400)
        source_type = str(payload.get("source_type") or "manual_csv").strip()
        if source_type not in {"manual_csv", "semantic_domain", "api", "webhook"}:
            raise ForgeError("source_type must be one of manual_csv, semantic_domain, api, or webhook.", status_code=400)
        row = self._resource_repository.create_resource_set(
            workspace_id=workspace_id,
            resource_set_key=resource_set_key,
            display_name=display_name,
            description=str(payload.get("description")).strip() if payload.get("description") is not None else None,
            source_type=source_type,
            settings=payload.get("settings") if isinstance(payload.get("settings"), dict) else {},
            created_by=str(actor_user_id or "").strip() or None,
        )
        return self._serialize_resource_set(row)

    def update_resource_set(
        self,
        *,
        workspace_id: str,
        resource_set_id: int,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        if "enabled" not in payload:
            raise ForgeError("enabled is required.", status_code=400)
        resource_set = self._resource_repository.get_resource_set(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
        )
        if resource_set is None:
            raise ForgeError(f"Resource set '{resource_set_id}' was not found.", status_code=404)
        enabled = bool(payload.get("enabled"))
        updated = self._resource_repository.update_resource_set_enabled(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
            enabled=enabled,
            updated_by=str(actor_user_id or "").strip() or None,
        )
        if not updated:
            raise ForgeError(f"Resource set '{resource_set_id}' was not found.", status_code=404)
        updated_resource_set = dict(resource_set)
        updated_resource_set["enabled"] = enabled
        return self._serialize_resource_set(updated_resource_set)

    def delete_resource_set(self, *, workspace_id: str, resource_set_id: int, actor_user_id: str) -> dict[str, Any]:
        resource_set = self._resource_repository.get_resource_set(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
        )
        if resource_set is None:
            raise ForgeError(f"Resource set '{resource_set_id}' was not found.", status_code=404)
        archived = self._resource_repository.archive_resource_set(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
            updated_by=str(actor_user_id or "").strip() or None,
        )
        if not archived:
            raise ForgeError(f"Resource set '{resource_set_id}' was not found.", status_code=404)
        return {"deleted": True, "resource_set_id": resource_set_id}

    def list_resource_records(
        self,
        *,
        workspace_id: str,
        resource_set_id: int,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        safe_limit = min(max(int(limit or 100), 1), 500)
        safe_offset = max(int(offset or 0), 0)
        rows = self._resource_repository.list_snapshot_records(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
            limit=safe_limit,
            offset=safe_offset,
        )
        return {
            "resource_set_id": int(resource_set_id),
            "limit": safe_limit,
            "offset": safe_offset,
            "records": [self._serialize_resource_record(row) for row in rows],
        }

    def update_resource_record(
        self,
        *,
        workspace_id: str,
        resource_set_id: int,
        record_id: int,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        existing = self._resource_repository.get_snapshot_record_by_id(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
            record_id=record_id,
        )
        if existing is None:
            raise ForgeError(f"Resource record '{record_id}' was not found.", status_code=404)
        if not isinstance(payload, dict):
            raise ForgeError("record payload must be an object.", status_code=400)
        normalized = self._normalize_resource_record_update(existing=existing, payload=payload)
        updated = self._resource_repository.update_snapshot_record(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
            record_id=record_id,
            **normalized,
        )
        if not updated:
            raise ForgeError(f"Resource record '{record_id}' was not found.", status_code=404)
        updated_record = self._resource_repository.get_snapshot_record_by_id(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
            record_id=record_id,
        )
        return self._serialize_resource_record(updated_record or {**existing, **normalized})

    def delete_resource_record(self, *, workspace_id: str, resource_set_id: int, record_id: int, actor_user_id: str) -> dict[str, Any]:
        existing = self._resource_repository.get_snapshot_record_by_id(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
            record_id=record_id,
        )
        if existing is None:
            raise ForgeError(f"Resource record '{record_id}' was not found.", status_code=404)
        deleted = self._resource_repository.delete_snapshot_record(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
            record_id=record_id,
        )
        if not deleted:
            raise ForgeError(f"Resource record '{record_id}' was not found.", status_code=404)
        return {"deleted": True, "resource_set_id": int(resource_set_id), "resource_record_id": int(record_id)}

    def list_resource_snapshot_batches(
        self,
        *,
        workspace_id: str,
        resource_set_id: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        safe_limit = min(max(int(limit or 25), 1), 100)
        return [
            self._serialize_snapshot_batch(row)
            for row in self._resource_repository.list_snapshot_batches(
                workspace_id=workspace_id,
                resource_set_id=resource_set_id,
                limit=safe_limit,
            )
        ]

    def get_resource_profile(
        self,
        *,
        workspace_id: str,
        resource_set_id: int,
        snapshot_batch_id: int,
        source_record_key: str,
    ) -> dict[str, Any]:
        record = self._resource_repository.get_snapshot_record(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
            snapshot_batch_id=snapshot_batch_id,
            source_record_key=source_record_key,
        )
        if record is None:
            raise ForgeError("FlowForge resource profile was not found.", status_code=404)
        return {
            "resource_set_id": int(resource_set_id),
            "snapshot_batch_id": int(snapshot_batch_id),
            "source_record_key": str(source_record_key or "").strip(),
            "record": self._serialize_resource_record(record),
        }

    def create_manual_resource_snapshot(
        self,
        *,
        workspace_id: str,
        resource_set_id: int,
        payload: dict[str, Any],
        actor_user_id: str,
    ) -> dict[str, Any]:
        raw_records = payload.get("records")
        if not isinstance(raw_records, list) or not raw_records:
            raise ForgeError("records must contain at least one resource record.", status_code=400)
        mode = str(payload.get("mode") or "production").strip()
        if mode not in {"production", "test"}:
            raise ForgeError("mode must be production or test.", status_code=400)
        resource_set = self._resource_repository.get_resource_set(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
        )
        if resource_set is None:
            raise ForgeError(f"Resource set '{resource_set_id}' was not found.", status_code=404)
        batch_key = str(payload.get("batch_key") or f"manual-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}").strip()
        should_activate = bool(payload.get("activate", True))
        snapshot_batch_id = int(resource_set.get("active_snapshot_batch_id") or 0) if should_activate else 0
        created_new_batch = snapshot_batch_id <= 0
        if created_new_batch:
            snapshot_batch_id = self._resource_repository.create_snapshot_batch(
                workspace_id=workspace_id,
                resource_set_id=resource_set_id,
                batch_key=batch_key,
                source_type="manual_csv",
                mode=mode,
                record_count=len(raw_records),
                source_ref=payload.get("source_ref") if isinstance(payload.get("source_ref"), dict) else None,
                created_by=str(actor_user_id or "").strip() or None,
            )
        valid_count = 0
        invalid_count = 0
        for record in raw_records:
            if not isinstance(record, dict):
                invalid_count += 1
                continue
            try:
                normalized = self._normalize_resource_record(record)
                source_record_key = normalized.pop("source_record_key")
                self._resource_repository.upsert_snapshot_record(
                    workspace_id=workspace_id,
                    resource_set_id=resource_set_id,
                    snapshot_batch_id=snapshot_batch_id,
                    source_record_key=source_record_key,
                    **normalized,
                )
                valid_count += 1
            except ForgeError:
                invalid_count += 1
        if created_new_batch:
            self._resource_repository.complete_snapshot_batch(
                workspace_id=workspace_id,
                snapshot_batch_id=snapshot_batch_id,
                valid_count=valid_count,
                invalid_count=invalid_count,
                summary={"message": "Manual snapshot processed.", "batch_key": batch_key, "upsert": False},
            )
        activated = bool(resource_set.get("active_snapshot_batch_id")) and should_activate and valid_count > 0
        if created_new_batch and should_activate and valid_count > 0:
            activated = self._resource_repository.activate_snapshot_batch(
                workspace_id=workspace_id,
                resource_set_id=resource_set_id,
                snapshot_batch_id=snapshot_batch_id,
            )
        return {
            "resource_set_id": int(resource_set_id),
            "snapshot_batch_id": snapshot_batch_id,
            "status": "completed",
            "record_count": len(raw_records),
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "activated": activated,
        }

    def _serialize_resource_set(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "workspace_id": row.get("workspace_id"),
            "resource_set_key": row.get("resource_set_key"),
            "display_name": row.get("display_name"),
            "description": row.get("description"),
            "source_type": row.get("source_type"),
            "enabled": bool(row.get("enabled")),
            "active_snapshot_batch_id": row.get("active_snapshot_batch_id"),
            "settings": row.get("settings") or row.get("settings_json") or {},
        }

    def _serialize_resource_record(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "workspace_id": row.get("workspace_id"),
            "resource_set_id": row.get("resource_set_id"),
            "snapshot_batch_id": row.get("snapshot_batch_id"),
            "source_record_key": row.get("source_record_key"),
            "display_name": row.get("display_name"),
            "primary_email": row.get("primary_email"),
            "primary_phone": row.get("primary_phone"),
            "status": row.get("status"),
            "effective_status": row.get("effective_status"),
            "availability_status": row.get("availability_status"),
            "capacity_total": self._json_safe_number(row.get("capacity_total")),
            "capacity_used": self._json_safe_number(row.get("capacity_used")),
            "capacity_available": self._json_safe_number(row.get("capacity_available")),
            "current_load": self._json_safe_number(row.get("current_load")),
            "service_area": row.get("service_area"),
            "timezone": row.get("timezone"),
            "source_missing": bool(row.get("source_missing")),
            "tags": row.get("tags") or row.get("tags_json") or [],
            "attributes": row.get("attributes") or row.get("attributes_json") or {},
            "normalized_profile": row.get("normalized_profile") or row.get("normalized_profile_json") or {},
            "validation_status": row.get("validation_status"),
            "validation_errors": row.get("validation_errors") or row.get("validation_errors_json") or [],
        }

    def _json_safe_number(self, value: Any) -> Any:
        if isinstance(value, Decimal):
            if value == value.to_integral_value():
                return int(value)
            return float(value)
        return value

    def _serialize_snapshot_batch(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("id"),
            "workspace_id": row.get("workspace_id"),
            "resource_set_id": row.get("resource_set_id"),
            "batch_key": row.get("batch_key"),
            "source_type": row.get("source_type"),
            "mode": row.get("mode"),
            "status": row.get("status"),
            "record_count": row.get("record_count"),
            "valid_count": row.get("valid_count"),
            "invalid_count": row.get("invalid_count"),
            "summary": row.get("summary") or row.get("summary_json") or {},
            "started_at": row.get("started_at"),
            "completed_at": row.get("completed_at"),
        }

    def _normalize_resource_record(self, record: dict[str, Any]) -> dict[str, Any]:
        source_record_key = str(record.get("source_record_key") or "").strip()
        if not source_record_key:
            raise ForgeError("Every resource record requires source_record_key.", status_code=400)
        capacity_total = record.get("capacity_total")
        capacity_used = record.get("capacity_used")
        capacity_available = record.get("capacity_available")
        if capacity_available is None and capacity_total is not None and capacity_used is not None:
            capacity_available = float(capacity_total) - float(capacity_used)
        normalized_profile = record.get("normalized_profile") if isinstance(record.get("normalized_profile"), dict) else {}
        normalized_profile = {
            **record,
            **normalized_profile,
        }
        return {
            "source_record_key": source_record_key,
            "display_name": self._optional_string(record.get("display_name")),
            "primary_email": self._optional_string(record.get("primary_email")),
            "primary_phone": self._optional_string(record.get("primary_phone")),
            "status": str(record.get("status") or "active").strip(),
            "effective_status": str(record.get("effective_status") or record.get("status") or "active").strip(),
            "availability_status": self._optional_string(record.get("availability_status")),
            "capacity_total": capacity_total,
            "capacity_used": capacity_used,
            "capacity_available": capacity_available,
            "current_load": record.get("current_load"),
            "service_area": self._optional_string(record.get("service_area")),
            "timezone": self._optional_string(record.get("timezone")),
            "tags": record.get("tags") if isinstance(record.get("tags"), list) else [],
            "attributes": record.get("attributes") if isinstance(record.get("attributes"), dict) else {},
            "normalized_profile": normalized_profile,
            "sensitive_profile": record.get("sensitive_profile") if isinstance(record.get("sensitive_profile"), dict) else None,
            "validation_status": "valid",
            "validation_errors": [],
            "source_missing": bool(record.get("source_missing")),
            "source_updated_at": record.get("source_updated_at"),
        }

    def _normalize_resource_record_update(self, *, existing: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        def pick(key: str, fallback: Any = None) -> Any:
            return payload[key] if key in payload else existing.get(key, fallback)

        source_record_key = str(pick("source_record_key", "") or "").strip()
        if not source_record_key:
            raise ForgeError("source_record_key is required.", status_code=400)
        capacity_total = pick("capacity_total")
        capacity_used = pick("capacity_used")
        capacity_available = pick("capacity_available")
        if capacity_available is None and capacity_total is not None and capacity_used is not None:
            capacity_available = float(capacity_total) - float(capacity_used)
        existing_normalized = existing.get("normalized_profile") or existing.get("normalized_profile_json") or {}
        payload_normalized = payload.get("normalized_profile") if isinstance(payload.get("normalized_profile"), dict) else {}
        normalized_profile = {
            **(existing_normalized if isinstance(existing_normalized, dict) else {}),
            **payload,
            **payload_normalized,
        }
        normalized_profile.pop("sensitive_profile", None)
        return {
            "source_record_key": source_record_key,
            "display_name": self._optional_string(pick("display_name")),
            "primary_email": self._optional_string(pick("primary_email")),
            "primary_phone": self._optional_string(pick("primary_phone")),
            "status": str(pick("status", "active") or "active").strip(),
            "effective_status": str(pick("effective_status", pick("status", "active")) or "active").strip(),
            "availability_status": self._optional_string(pick("availability_status")),
            "capacity_total": capacity_total,
            "capacity_used": capacity_used,
            "capacity_available": capacity_available,
            "current_load": pick("current_load"),
            "service_area": self._optional_string(pick("service_area")),
            "timezone": self._optional_string(pick("timezone")),
            "tags": pick("tags", existing.get("tags_json") or []) if isinstance(pick("tags", existing.get("tags_json") or []), list) else [],
            "attributes": pick("attributes", existing.get("attributes_json") or {})
            if isinstance(pick("attributes", existing.get("attributes_json") or {}), dict)
            else {},
            "normalized_profile": normalized_profile,
            "validation_status": str(pick("validation_status", "valid") or "valid").strip(),
            "validation_errors": pick("validation_errors", existing.get("validation_errors_json") or [])
            if isinstance(pick("validation_errors", existing.get("validation_errors_json") or []), list)
            else [],
            "source_missing": bool(pick("source_missing", False)),
            "source_updated_at": pick("source_updated_at"),
        }
