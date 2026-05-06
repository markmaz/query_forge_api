from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.features.flowforge.repositories import FlowForgeResourceRepository
from app.features.flowforge.runtime.node_executor import FlowForgeNodeExecutionError


@dataclass(frozen=True)
class ResourceImportValidationResult:
    valid_records: list[dict[str, Any]]
    invalid_rows: list[dict[str, Any]]
    summary: dict[str, Any]


class ResourceImportRecordNormalizer:
    def validate(self, rows: list[dict[str, Any]]) -> ResourceImportValidationResult:
        valid_records: list[dict[str, Any]] = []
        invalid_rows: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            try:
                valid_records.append(self.normalize(row))
            except FlowForgeNodeExecutionError as exc:
                invalid_rows.append(
                    {
                        "row_number": index,
                        "source_record_key": str(row.get("source_record_key") or "").strip() or None,
                        "errors": [str(exc)],
                    }
                )
        return ResourceImportValidationResult(
            valid_records=valid_records,
            invalid_rows=invalid_rows[:25],
            summary={
                "input_row_count": len(rows),
                "valid_row_count": len(valid_records),
                "invalid_row_count": len(invalid_rows),
                "invalid_rows": invalid_rows[:25],
            },
        )

    def normalize(self, record: dict[str, Any]) -> dict[str, Any]:
        source_record_key = str(record.get("source_record_key") or "").strip()
        if not source_record_key:
            raise FlowForgeNodeExecutionError("Every resource import row requires source_record_key.")
        capacity_total = self._numeric_or_none(record.get("capacity_total"))
        capacity_used = self._numeric_or_none(record.get("capacity_used"))
        capacity_available = self._numeric_or_none(record.get("capacity_available"))
        if capacity_available is None and capacity_total is not None and capacity_used is not None:
            capacity_available = capacity_total - capacity_used
        normalized_profile = record.get("normalized_profile") if isinstance(record.get("normalized_profile"), dict) else {}
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
            "current_load": self._numeric_or_none(record.get("current_load")),
            "service_area": self._optional_string(record.get("service_area")),
            "timezone": self._optional_string(record.get("timezone")),
            "tags": self._list_value(record.get("tags")),
            "attributes": record.get("attributes") if isinstance(record.get("attributes"), dict) else {},
            "normalized_profile": {**record, **normalized_profile},
            "sensitive_profile": record.get("sensitive_profile") if isinstance(record.get("sensitive_profile"), dict) else None,
            "validation_status": "valid",
            "validation_errors": [],
            "source_missing": bool(record.get("source_missing")),
            "source_updated_at": record.get("source_updated_at"),
        }

    def _list_value(self, value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if isinstance(value, str) and value.strip():
            return [part.strip() for part in value.split("|") if part.strip()]
        return []

    def _numeric_or_none(self, value: Any) -> Any:
        if value is None or value == "":
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise FlowForgeNodeExecutionError(f"Numeric import field contains invalid value '{value}'.") from None
        return int(number) if number == int(number) else number

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None


class ResourceSetActivationService:
    def __init__(
        self,
        *,
        resource_repository: FlowForgeResourceRepository | None = None,
        normalizer: ResourceImportRecordNormalizer | None = None,
    ) -> None:
        self._resource_repository = resource_repository or FlowForgeResourceRepository()
        self._normalizer = normalizer or ResourceImportRecordNormalizer()

    def validate(self, *, rows: list[dict[str, Any]]) -> ResourceImportValidationResult:
        return self._normalizer.validate(rows)

    def activate(
        self,
        *,
        workspace_id: str,
        resource_set_id: int,
        rows: list[dict[str, Any]],
        mode: str,
        source_ref: dict[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        resource_set = self._resource_repository.get_resource_set(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
        )
        if resource_set is None:
            raise FlowForgeNodeExecutionError(f"Resource set '{resource_set_id}' was not found.")
        validation = self.validate(rows=rows)
        if validation.invalid_rows:
            raise FlowForgeNodeExecutionError("Resource import contains invalid rows.")
        batch_key = f"import-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        snapshot_batch_id = self._resource_repository.create_snapshot_batch(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
            batch_key=batch_key,
            source_type="import",
            mode=mode,
            record_count=len(rows),
            source_ref=source_ref,
            created_by=actor_id,
        )
        for record in validation.valid_records:
            source_record_key = str(record.pop("source_record_key"))
            self._resource_repository.upsert_snapshot_record(
                workspace_id=workspace_id,
                resource_set_id=resource_set_id,
                snapshot_batch_id=snapshot_batch_id,
                source_record_key=source_record_key,
                **record,
            )
        self._resource_repository.complete_snapshot_batch(
            workspace_id=workspace_id,
            snapshot_batch_id=snapshot_batch_id,
            valid_count=len(validation.valid_records),
            invalid_count=0,
            summary={
                "message": "Import activated resource set snapshot.",
                "source_ref": source_ref,
            },
        )
        activated = self._resource_repository.activate_snapshot_batch(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
            snapshot_batch_id=snapshot_batch_id,
        )
        return {
            "resource_set_id": int(resource_set_id),
            "snapshot_batch_id": int(snapshot_batch_id),
            "valid_count": len(validation.valid_records),
            "invalid_count": 0,
            "activated": bool(activated),
        }
