from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.features.flowforge.repositories.common import bool_value as _bool, json_or_none as _json_or_none, json_value as _json_value, lastrowid as _lastrowid


class FlowForgeResourceRepository:
    _JSON_KEYS = {
        "tags_json",
        "attributes_json",
        "normalized_profile_json",
        "sensitive_profile_json",
        "validation_errors_json",
    }

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def list_resource_sets(self, *, workspace_id: str) -> list[dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_resource_sets
            WHERE workspace_id = :workspace_id
              AND archived_at IS NULL
            ORDER BY display_name ASC, id ASC
            """,
            {"workspace_id": str(workspace_id or "").strip()},
        )
        return [self._decode_resource_set(row) for row in rows]

    def get_resource_set(self, *, workspace_id: str, resource_set_id: int) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_resource_sets
            WHERE workspace_id = :workspace_id
              AND id = :resource_set_id
              AND archived_at IS NULL
            LIMIT 1
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "resource_set_id": int(resource_set_id),
            },
        )
        if not rows:
            return None
        return self._decode_resource_set(rows[0])

    def create_resource_set(
        self,
        *,
        workspace_id: str,
        resource_set_key: str,
        display_name: str,
        description: str | None,
        source_type: str,
        settings: dict[str, Any] | None,
        created_by: str | None,
    ) -> dict[str, Any]:
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_resource_sets (
              workspace_id,
              resource_set_key,
              display_name,
              description,
              source_type,
              settings_json,
              created_by
            ) VALUES (
              :workspace_id,
              :resource_set_key,
              :display_name,
              :description,
              :source_type,
              :settings_json,
              :created_by
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "resource_set_key": str(resource_set_key or "").strip(),
                "display_name": str(display_name or "").strip(),
                "description": description,
                "source_type": str(source_type or "manual_csv").strip(),
                "settings_json": _json_or_none(settings),
                "created_by": created_by,
            },
        )
        return {
            "id": _lastrowid(result),
            "workspace_id": str(workspace_id or "").strip(),
            "resource_set_key": str(resource_set_key or "").strip(),
            "display_name": str(display_name or "").strip(),
            "description": description,
            "source_type": str(source_type or "manual_csv").strip(),
            "enabled": True,
            "active_snapshot_batch_id": None,
            "settings_json": settings or {},
        }

    def update_resource_set_enabled(
        self,
        *,
        workspace_id: str,
        resource_set_id: int,
        enabled: bool,
        updated_by: str | None,
    ) -> bool:
        updated = self._sql.execute_write(
            """
            UPDATE flowforge_resource_sets
            SET enabled = :enabled,
                updated_by = :updated_by,
                updated_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND id = :resource_set_id
              AND archived_at IS NULL
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "resource_set_id": int(resource_set_id),
                "enabled": 1 if enabled else 0,
                "updated_by": updated_by,
            },
        )
        return int(updated or 0) > 0

    def archive_resource_set(
        self,
        *,
        workspace_id: str,
        resource_set_id: int,
        updated_by: str | None,
    ) -> bool:
        updated = self._sql.execute_write(
            """
            UPDATE flowforge_resource_sets
            SET enabled = 0,
                archived_at = CURRENT_TIMESTAMP,
                updated_by = :updated_by,
                updated_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND id = :resource_set_id
              AND archived_at IS NULL
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "resource_set_id": int(resource_set_id),
                "updated_by": updated_by,
            },
        )
        return int(updated or 0) > 0

    def list_snapshot_records(
        self,
        *,
        workspace_id: str,
        resource_set_id: int,
        limit: int,
        offset: int,
    ) -> list[dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT records.*
            FROM flowforge_resource_snapshot_records records
            INNER JOIN flowforge_resource_sets sets
              ON sets.workspace_id = records.workspace_id
             AND sets.id = records.resource_set_id
             AND sets.active_snapshot_batch_id = records.snapshot_batch_id
            WHERE records.workspace_id = :workspace_id
              AND records.resource_set_id = :resource_set_id
              AND sets.archived_at IS NULL
            ORDER BY records.display_name ASC, records.source_record_key ASC
            LIMIT :limit OFFSET :offset
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "resource_set_id": int(resource_set_id),
                "limit": int(limit),
                "offset": int(offset),
            },
        )
        return [self._decode_snapshot_record(row) for row in rows]

    def upsert_snapshot_record(
        self,
        *,
        workspace_id: str,
        resource_set_id: int,
        snapshot_batch_id: int,
        source_record_key: str,
        **payload: Any,
    ) -> int:
        existing = self.get_snapshot_record(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
            snapshot_batch_id=snapshot_batch_id,
            source_record_key=source_record_key,
        )
        if existing:
            update_payload = {key: value for key, value in payload.items() if key != "sensitive_profile"}
            self.update_snapshot_record(
                workspace_id=workspace_id,
                resource_set_id=resource_set_id,
                record_id=int(existing["id"]),
                source_record_key=source_record_key,
                **update_payload,
            )
            return int(existing["id"])
        return self.create_snapshot_record(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
            snapshot_batch_id=snapshot_batch_id,
            source_record_key=source_record_key,
            **payload,
        )

    def get_snapshot_record_by_id(self, *, workspace_id: str, resource_set_id: int, record_id: int) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_resource_snapshot_records
            WHERE workspace_id = :workspace_id
              AND resource_set_id = :resource_set_id
              AND id = :record_id
            LIMIT 1
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "resource_set_id": int(resource_set_id),
                "record_id": int(record_id),
            },
        )
        if not rows:
            return None
        return self._decode_snapshot_record(rows[0])

    def update_snapshot_record(
        self,
        *,
        workspace_id: str,
        resource_set_id: int,
        record_id: int,
        source_record_key: str,
        display_name: str | None,
        primary_email: str | None,
        primary_phone: str | None,
        status: str,
        effective_status: str,
        availability_status: str | None,
        capacity_total: Any,
        capacity_used: Any,
        capacity_available: Any,
        current_load: Any,
        service_area: str | None,
        timezone: str | None,
        tags: list[Any] | None,
        attributes: dict[str, Any] | None,
        normalized_profile: dict[str, Any],
        validation_status: str,
        validation_errors: list[Any] | None,
        source_missing: bool,
        source_updated_at: Any,
    ) -> bool:
        updated = self._sql.execute_write(
            """
            UPDATE flowforge_resource_snapshot_records
            SET source_record_key = :source_record_key,
                display_name = :display_name,
                primary_email = :primary_email,
                primary_phone = :primary_phone,
                status = :status,
                effective_status = :effective_status,
                availability_status = :availability_status,
                capacity_total = :capacity_total,
                capacity_used = :capacity_used,
                capacity_available = :capacity_available,
                current_load = :current_load,
                service_area = :service_area,
                timezone = :timezone,
                tags_json = :tags_json,
                attributes_json = :attributes_json,
                normalized_profile_json = :normalized_profile_json,
                validation_status = :validation_status,
                validation_errors_json = :validation_errors_json,
                source_missing = :source_missing,
                source_updated_at = :source_updated_at
            WHERE workspace_id = :workspace_id
              AND resource_set_id = :resource_set_id
              AND id = :record_id
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "resource_set_id": int(resource_set_id),
                "record_id": int(record_id),
                "source_record_key": str(source_record_key or "").strip(),
                "display_name": display_name,
                "primary_email": primary_email,
                "primary_phone": primary_phone,
                "status": str(status or "active").strip(),
                "effective_status": str(effective_status or "active").strip(),
                "availability_status": availability_status,
                "capacity_total": capacity_total,
                "capacity_used": capacity_used,
                "capacity_available": capacity_available,
                "current_load": current_load,
                "service_area": service_area,
                "timezone": timezone,
                "tags_json": _json_or_none(tags or []),
                "attributes_json": _json_or_none(attributes or {}),
                "normalized_profile_json": _json_or_none(normalized_profile),
                "validation_status": str(validation_status or "valid").strip(),
                "validation_errors_json": _json_or_none(validation_errors or []),
                "source_missing": 1 if source_missing else 0,
                "source_updated_at": source_updated_at,
            },
        )
        return int(updated or 0) > 0

    def delete_snapshot_record(self, *, workspace_id: str, resource_set_id: int, record_id: int) -> bool:
        deleted = self._sql.execute_write(
            """
            DELETE FROM flowforge_resource_snapshot_records
            WHERE workspace_id = :workspace_id
              AND resource_set_id = :resource_set_id
              AND id = :record_id
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "resource_set_id": int(resource_set_id),
                "record_id": int(record_id),
            },
        )
        return int(deleted or 0) > 0

    def list_snapshot_records_for_batch(
        self,
        *,
        workspace_id: str,
        resource_set_id: int,
        snapshot_batch_id: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_resource_snapshot_records
            WHERE workspace_id = :workspace_id
              AND resource_set_id = :resource_set_id
              AND snapshot_batch_id = :snapshot_batch_id
            ORDER BY display_name ASC, source_record_key ASC
            LIMIT :limit
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "resource_set_id": int(resource_set_id),
                "snapshot_batch_id": int(snapshot_batch_id),
                "limit": int(limit),
            },
        )
        return [self._decode_snapshot_record(row) for row in rows]

    def list_snapshot_batches(self, *, workspace_id: str, resource_set_id: int, limit: int) -> list[dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_resource_snapshot_batches
            WHERE workspace_id = :workspace_id
              AND resource_set_id = :resource_set_id
            ORDER BY started_at DESC, id DESC
            LIMIT :limit
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "resource_set_id": int(resource_set_id),
                "limit": int(limit),
            },
        )
        return [self._decode_snapshot_batch(row) for row in rows]

    def create_snapshot_batch(
        self,
        *,
        workspace_id: str,
        resource_set_id: int,
        batch_key: str,
        source_type: str,
        mode: str,
        record_count: int,
        source_ref: dict[str, Any] | None,
        created_by: str | None,
    ) -> int:
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_resource_snapshot_batches (
              workspace_id,
              resource_set_id,
              batch_key,
              source_type,
              mode,
              record_count,
              source_ref_json,
              created_by
            ) VALUES (
              :workspace_id,
              :resource_set_id,
              :batch_key,
              :source_type,
              :mode,
              :record_count,
              :source_ref_json,
              :created_by
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "resource_set_id": int(resource_set_id),
                "batch_key": str(batch_key or "").strip(),
                "source_type": str(source_type or "manual_csv").strip(),
                "mode": str(mode or "production").strip(),
                "record_count": int(record_count),
                "source_ref_json": _json_or_none(source_ref),
                "created_by": created_by,
            },
        )
        return _lastrowid(result)

    def create_snapshot_record(
        self,
        *,
        workspace_id: str,
        resource_set_id: int,
        snapshot_batch_id: int,
        source_record_key: str,
        display_name: str | None,
        primary_email: str | None,
        primary_phone: str | None,
        status: str,
        effective_status: str,
        availability_status: str | None,
        capacity_total: Any,
        capacity_used: Any,
        capacity_available: Any,
        current_load: Any,
        service_area: str | None,
        timezone: str | None,
        tags: list[Any] | None,
        attributes: dict[str, Any] | None,
        normalized_profile: dict[str, Any],
        sensitive_profile: dict[str, Any] | None,
        validation_status: str,
        validation_errors: list[Any] | None,
        source_missing: bool,
        source_updated_at: datetime | None,
    ) -> int:
        result = self._sql.execute_insert(
            """
            INSERT INTO flowforge_resource_snapshot_records (
              workspace_id,
              resource_set_id,
              snapshot_batch_id,
              source_record_key,
              display_name,
              primary_email,
              primary_phone,
              status,
              effective_status,
              availability_status,
              capacity_total,
              capacity_used,
              capacity_available,
              current_load,
              service_area,
              timezone,
              tags_json,
              attributes_json,
              normalized_profile_json,
              sensitive_profile_json,
              validation_status,
              validation_errors_json,
              source_missing,
              source_updated_at
            ) VALUES (
              :workspace_id,
              :resource_set_id,
              :snapshot_batch_id,
              :source_record_key,
              :display_name,
              :primary_email,
              :primary_phone,
              :status,
              :effective_status,
              :availability_status,
              :capacity_total,
              :capacity_used,
              :capacity_available,
              :current_load,
              :service_area,
              :timezone,
              :tags_json,
              :attributes_json,
              :normalized_profile_json,
              :sensitive_profile_json,
              :validation_status,
              :validation_errors_json,
              :source_missing,
              :source_updated_at
            )
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "resource_set_id": int(resource_set_id),
                "snapshot_batch_id": int(snapshot_batch_id),
                "source_record_key": str(source_record_key or "").strip(),
                "display_name": display_name,
                "primary_email": primary_email,
                "primary_phone": primary_phone,
                "status": str(status or "active").strip(),
                "effective_status": str(effective_status or "active").strip(),
                "availability_status": availability_status,
                "capacity_total": capacity_total,
                "capacity_used": capacity_used,
                "capacity_available": capacity_available,
                "current_load": current_load,
                "service_area": service_area,
                "timezone": timezone,
                "tags_json": _json_or_none(tags or []),
                "attributes_json": _json_or_none(attributes or {}),
                "normalized_profile_json": _json_or_none(normalized_profile),
                "sensitive_profile_json": _json_or_none(sensitive_profile),
                "validation_status": str(validation_status or "valid").strip(),
                "validation_errors_json": _json_or_none(validation_errors or []),
                "source_missing": 1 if source_missing else 0,
                "source_updated_at": source_updated_at,
            },
        )
        return _lastrowid(result)

    def complete_snapshot_batch(
        self,
        *,
        workspace_id: str,
        snapshot_batch_id: int,
        valid_count: int,
        invalid_count: int,
        summary: dict[str, Any] | None,
    ) -> bool:
        updated = self._sql.execute_write(
            """
            UPDATE flowforge_resource_snapshot_batches
            SET status = 'completed',
                valid_count = :valid_count,
                invalid_count = :invalid_count,
                summary_json = :summary_json,
                completed_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND id = :snapshot_batch_id
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "snapshot_batch_id": int(snapshot_batch_id),
                "valid_count": int(valid_count),
                "invalid_count": int(invalid_count),
                "summary_json": _json_or_none(summary),
            },
        )
        return int(updated or 0) > 0

    def activate_snapshot_batch(self, *, workspace_id: str, resource_set_id: int, snapshot_batch_id: int) -> bool:
        updated = self._sql.execute_write(
            """
            UPDATE flowforge_resource_sets
            SET active_snapshot_batch_id = :snapshot_batch_id,
                updated_at = CURRENT_TIMESTAMP
            WHERE workspace_id = :workspace_id
              AND id = :resource_set_id
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "resource_set_id": int(resource_set_id),
                "snapshot_batch_id": int(snapshot_batch_id),
            },
        )
        return int(updated or 0) > 0

    def mark_resource_offered(self, *, workspace_id: str, resource_set_id: int, source_record_key: str) -> bool:
        return self._upsert_runtime_state(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
            source_record_key=source_record_key,
            assignment_delta=0,
            offer_delta=1,
            timestamp_column="last_offered_at",
        )

    def mark_resource_assigned(self, *, workspace_id: str, resource_set_id: int, source_record_key: str) -> bool:
        return self._upsert_runtime_state(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
            source_record_key=source_record_key,
            assignment_delta=1,
            offer_delta=-1,
            timestamp_column="last_accepted_at",
        )

    def mark_resource_declined(self, *, workspace_id: str, resource_set_id: int, source_record_key: str) -> bool:
        return self._upsert_runtime_state(
            workspace_id=workspace_id,
            resource_set_id=resource_set_id,
            source_record_key=source_record_key,
            assignment_delta=0,
            offer_delta=-1,
            timestamp_column="last_declined_at",
        )

    def _upsert_runtime_state(
        self,
        *,
        workspace_id: str,
        resource_set_id: int,
        source_record_key: str,
        assignment_delta: int,
        offer_delta: int,
        timestamp_column: str,
    ) -> bool:
        count = self._sql.execute_write(
            f"""
            INSERT INTO flowforge_resource_runtime_state (
              workspace_id,
              resource_set_id,
              source_record_key,
              active_offer_count,
              active_assignment_count,
              {timestamp_column}
            ) VALUES (
              :workspace_id,
              :resource_set_id,
              :source_record_key,
              GREATEST(0, :offer_delta),
              GREATEST(0, :assignment_delta),
              CURRENT_TIMESTAMP
            )
            ON DUPLICATE KEY UPDATE
              active_offer_count = GREATEST(0, active_offer_count + :offer_delta),
              active_assignment_count = GREATEST(0, active_assignment_count + :assignment_delta),
              {timestamp_column} = CURRENT_TIMESTAMP
            """
            ,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "resource_set_id": int(resource_set_id),
                "source_record_key": str(source_record_key or "").strip(),
                "offer_delta": int(offer_delta),
                "assignment_delta": int(assignment_delta),
            },
        )
        return bool(count)

    def get_snapshot_record(
        self,
        *,
        workspace_id: str,
        resource_set_id: int,
        snapshot_batch_id: int,
        source_record_key: str,
    ) -> dict[str, Any] | None:
        rows = self._sql.execute_query_mappings(
            """
            SELECT *
            FROM flowforge_resource_snapshot_records
            WHERE workspace_id = :workspace_id
              AND resource_set_id = :resource_set_id
              AND snapshot_batch_id = :snapshot_batch_id
              AND source_record_key = :source_record_key
            LIMIT 1
            """,
            {
                "workspace_id": str(workspace_id or "").strip(),
                "resource_set_id": int(resource_set_id),
                "snapshot_batch_id": int(snapshot_batch_id),
                "source_record_key": str(source_record_key or "").strip(),
            },
        )
        if not rows:
            return None
        return self._decode_snapshot_record(rows[0])

    def _decode_resource_set(self, raw: dict[str, Any]) -> dict[str, Any]:
        row = dict(raw)
        row["enabled"] = _bool(row.get("enabled"))
        row["settings_json"] = _json_value(row.get("settings_json")) or {}
        row["refresh_schedule_json"] = _json_value(row.get("refresh_schedule_json")) or None
        return row

    def _decode_snapshot_batch(self, raw: dict[str, Any]) -> dict[str, Any]:
        row = dict(raw)
        row["source_ref_json"] = _json_value(row.get("source_ref_json")) or None
        row["summary_json"] = _json_value(row.get("summary_json")) or {}
        return row

    def _decode_snapshot_record(self, raw: dict[str, Any]) -> dict[str, Any]:
        row = dict(raw)
        row["source_missing"] = _bool(row.get("source_missing"))
        for key in self._JSON_KEYS:
            row[key] = _json_value(row.get(key))
        return row
