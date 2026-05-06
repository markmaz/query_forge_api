from __future__ import annotations

from typing import Any

from app.features.flowforge.repositories.common import bool_value as _bool, json_value as _json_value


class FlowForgeDataMovementDecoderMixin:
    _DATASET_JSON_KEYS = {"storage_ref_json", "schema_json"}
    _AUDIT_JSON_KEYS = {"request_json", "result_json"}

    def _decode_dataset_artifact(self, row: dict[str, Any]) -> dict[str, Any]:
        decoded = dict(row)
        for key in self._DATASET_JSON_KEYS:
            decoded[key] = _json_value(decoded.get(key)) or {}
        for key in ("id", "run_id", "row_count", "byte_count"):
            if decoded.get(key) is not None:
                decoded[key] = int(decoded[key])
        return decoded

    def _decode_audit(self, row: dict[str, Any]) -> dict[str, Any]:
        decoded = dict(row)
        for key in self._AUDIT_JSON_KEYS:
            decoded[key] = _json_value(decoded.get(key)) or {}
        for key in ("id", "run_id", "dataset_artifact_id", "resource_set_id"):
            if decoded.get(key) is not None:
                decoded[key] = int(decoded[key])
        return decoded

    def _decode_allowlist(self, row: dict[str, Any]) -> dict[str, Any]:
        decoded = dict(row)
        decoded["enabled"] = _bool(decoded.get("enabled"))
        decoded["config_json"] = _json_value(decoded.get("config_json")) or {}
        if decoded.get("id") is not None:
            decoded["id"] = int(decoded["id"])
        return decoded

    def _decode_schedule_run(self, row: dict[str, Any]) -> dict[str, Any]:
        decoded = dict(row)
        decoded["trigger_payload_json"] = _json_value(decoded.get("trigger_payload_json")) or {}
        for key in ("id", "workflow_definition_id", "workflow_version_id", "run_id"):
            if decoded.get(key) is not None:
                decoded[key] = int(decoded[key])
        return decoded
