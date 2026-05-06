from __future__ import annotations

import re
from typing import Any

from app.exceptions.forge_error import ForgeError


class FlowForgeDataMovementValidationMixin:
    _KEY_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")
    _ARTIFACT_STATUSES = {"pending", "ready", "failed", "expired"}
    _AUDIT_ACTION_TYPES = {"query_extract", "export", "import", "map_transform", "approval"}
    _AUDIT_STATUSES = {"started", "completed", "failed", "canceled"}
    _SOURCE_TYPES = {"manual_upload", "sftp", "api", "webhook", "jotform"}
    _DESTINATION_TYPES = {"email", "sftp", "s3_compatible", "api", "local_file_test"}
    _ALLOWLIST_MODES = {"test", "production"}

    def _optional_non_negative_int(self, value: Any, *, field_name: str) -> int | None:
        if value is None or value == "":
            return None
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ForgeError(f"{field_name} must be a non-negative integer.", status_code=400) from None
        if number < 0:
            raise ForgeError(f"{field_name} must be a non-negative integer.", status_code=400)
        return number

    def _require_allowlist_type(self, *, payload: dict[str, Any], field_name: str, allowed: set[str]) -> str:
        if not isinstance(payload, dict):
            raise ForgeError("payload must be an object.", status_code=400)
        value = str(payload.get(field_name) or "").strip()
        if value not in allowed:
            options = ", ".join(sorted(allowed))
            raise ForgeError(f"{field_name} must be one of {options}.", status_code=400)
        return value

    def _require_data_movement_key(self, value: Any, *, field_name: str) -> str:
        key = str(value or "").strip()
        if not key:
            raise ForgeError(f"{field_name} is required.", status_code=400)
        if not self._KEY_PATTERN.match(key):
            raise ForgeError(
                f"{field_name} must start with a letter or number and contain only letters, numbers, dots, underscores, colons, or hyphens.",
                status_code=400,
            )
        return key

    def _require_allowlist_mode(self, value: Any) -> str:
        mode = str(value or "test").strip()
        if mode not in self._ALLOWLIST_MODES:
            raise ForgeError("mode must be test or production.", status_code=400)
        return mode
