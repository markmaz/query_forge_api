from __future__ import annotations

import re
from typing import Any

VALID_FIELD_TYPES = {"text", "number", "boolean", "date", "datetime", "email", "phone", "json", "unknown"}
VALID_TRANSFORMS = {"copy", "concat", "template"}


def draft_workflow_value_schema(source_fields: list[dict[str, Any]]) -> dict[str, Any]:
    fields = [
        _field_from_source(source_field)
        for source_field in source_fields
        if isinstance(source_field, dict) and str(source_field.get("path") or "").strip()
    ]
    return normalize_workflow_value_schema({"fields": fields})


def normalize_workflow_value_schema(value: Any) -> dict[str, Any]:
    raw_fields = value.get("fields") if isinstance(value, dict) else value
    if not isinstance(raw_fields, list):
        raw_fields = []
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_fields:
        if not isinstance(item, dict):
            continue
        key = _normalize_key(item.get("key") or item.get("path") or item.get("target"))
        if not key or key in seen:
            continue
        seen.add(key)
        source_paths = _source_paths(item.get("source_paths") or item.get("sources") or item.get("source"))
        field_type = str(item.get("type") or "text").strip().lower()
        if field_type not in VALID_FIELD_TYPES:
            field_type = "unknown"
        transform = str(item.get("transform") or "copy").strip().lower()
        if transform not in VALID_TRANSFORMS:
            transform = "copy"
        fields.append(
            {
                "key": key,
                "label": str(item.get("label") or _label_from_key(key)).strip(),
                "type": field_type,
                "required": bool(item.get("required")),
                "sensitive": bool(item.get("sensitive")),
                "source_paths": source_paths,
                "transform": transform,
                "separator": str(item.get("separator") if item.get("separator") is not None else " ").strip(),
                "template": str(item.get("template") or "").strip(),
                "expose_to_templates": bool(item.get("expose_to_templates", True)),
            }
        )
    return {"fields": fields}


def _field_from_source(source_field: dict[str, Any]) -> dict[str, Any]:
    path = str(source_field.get("path") or "").strip().strip(".")
    label = str(source_field.get("label") or _label_from_path(path)).strip()
    field_type = str(source_field.get("type") or "text").strip().lower()
    return {
        "key": _key_from_source(path=path, label=label, field_type=field_type),
        "label": label,
        "type": field_type if field_type in VALID_FIELD_TYPES else "unknown",
        "required": bool(source_field.get("required")),
        "sensitive": bool(source_field.get("sensitive")),
        "source_paths": [path],
        "transform": "copy",
        "separator": " ",
        "template": "",
        "expose_to_templates": True,
    }


def _key_from_source(*, path: str, label: str, field_type: str) -> str:
    haystack = f"{path} {label}".lower()
    if field_type == "email" or "email" in haystack:
        return "values.patient.email"
    if field_type == "phone" or "phone" in haystack:
        return "values.patient.phone"
    if "full name" in haystack or "patient name" in haystack or haystack.endswith(" name"):
        return "values.patient.full_name"
    return f"values.intake.{_slug(path or label)}"


def _normalize_key(value: Any) -> str:
    key = str(value or "").strip().strip(".")
    if not key:
        return ""
    if key.startswith("values."):
        return ".".join(_slug(piece) for piece in key.split(".") if piece)
    return f"values.{_slug(key)}"


def _source_paths(value: Any) -> list[str]:
    raw_values = value if isinstance(value, list) else [value]
    paths: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        path = str(item or "").strip().strip(".")
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def _label_from_key(key: str) -> str:
    return _label_from_path(key.removeprefix("values."))


def _label_from_path(path: str) -> str:
    return path.replace(".", " ").replace("_", " ").title()


def _slug(value: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(value or ""))
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()
    return text or "field"
