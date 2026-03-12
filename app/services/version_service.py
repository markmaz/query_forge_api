from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from app.exceptions.forge_error import ForgeError


class VersionService:
    def __init__(self, *, version_file: Path | None = None) -> None:
        self._version_file = version_file or Path(__file__).resolve().parents[2] / "version.json"

    def get_version_payload(self) -> Dict[str, Any]:
        try:
            raw = self._version_file.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ForgeError("version.json not found", status_code=500) from exc
        except OSError as exc:
            raise ForgeError("Unable to read version.json", status_code=500) from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ForgeError("version.json is not valid JSON", status_code=500) from exc

        if isinstance(parsed, dict):
            if not str(parsed.get("version") or "").strip():
                raise ForgeError("version.json must contain a non-empty 'version' value", status_code=500)
            return dict(parsed)

        if isinstance(parsed, str) and parsed.strip():
            return {"version": parsed.strip()}

        raise ForgeError("version.json must contain a version string or object", status_code=500)

