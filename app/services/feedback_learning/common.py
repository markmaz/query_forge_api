from __future__ import annotations

from typing import Any, Mapping, Optional


def optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def derive_override_key(*, change_type: str, payload_json: Mapping[str, Any]) -> str:
    if change_type == "add_alias":
        return optional_text(payload_json.get("alias_key") or payload_json.get("alias")) or change_type
    if change_type == "add_domain_example_prompt":
        return optional_text(payload_json.get("example_key") or payload_json.get("prompt_key") or payload_json.get("prompt")) or change_type
    return (
        optional_text(
            payload_json.get("override_key")
            or payload_json.get("hint")
            or payload_json.get("phrase")
            or payload_json.get("note")
        )
        or change_type
    )


__all__ = ["derive_override_key", "optional_text"]
