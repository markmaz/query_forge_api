from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class MapTransformResult:
    rows: list[dict[str, Any]]
    columns: list[dict[str, Any]]
    rejected_rows: list[dict[str, Any]]
    validation_summary: dict[str, Any]


@dataclass(frozen=True)
class ContextTransformResult:
    context_update: dict[str, Any]
    communication_context: dict[str, Any]
    communication_fields: list[str]
    validation_summary: dict[str, Any]


class MapTransformEngine:
    def transform(
        self, *, rows: list[dict[str, Any]], config: dict[str, Any]
    ) -> MapTransformResult:
        field_mapping = config.get("field_mapping") or config.get("mapping") or {}
        validations = config.get("validations") or []
        if not isinstance(validations, list):
            validations = []

        mapped_rows = [
            self._map_row(
                row=row,
                field_mapping=field_mapping,
                include_unmapped=bool(config.get("include_unmapped")),
            )
            for row in rows
        ]
        accepted_rows: list[dict[str, Any]] = []
        rejected_rows: list[dict[str, Any]] = []
        for index, row in enumerate(mapped_rows):
            errors = self._validate_row(row=row, validations=validations)
            if errors:
                rejected_rows.append({"index": index, "errors": errors, "row": row})
            else:
                accepted_rows.append(row)

        return MapTransformResult(
            rows=accepted_rows,
            columns=self._columns_from_rows(accepted_rows or mapped_rows),
            rejected_rows=rejected_rows,
            validation_summary={
                "input_row_count": len(rows),
                "accepted_row_count": len(accepted_rows),
                "rejected_row_count": len(rejected_rows),
                "validation_count": len(validations),
                "rejected_rows": rejected_rows[:25],
            },
        )

    def transform_context(self, *, context: dict[str, Any], config: dict[str, Any]) -> ContextTransformResult:
        field_mapping = config.get("field_mapping") or config.get("mapping") or {}
        mapped = self._map_context(context=context, field_mapping=field_mapping)
        validations = config.get("validations") or []
        if not isinstance(validations, list):
            validations = []
        context_update = self._nested_from_flat(mapped)
        errors = self._validate_row(row=context_update, validations=validations)
        if errors:
            return ContextTransformResult(
                context_update={},
                communication_context={},
                communication_fields=[],
                validation_summary={
                    "input_context": "run_context",
                    "mapped_field_count": len(mapped),
                    "accepted": False,
                    "validation_count": len(validations),
                    "errors": errors,
                },
            )

        communication_fields = self._communication_fields(config=config, mapped=mapped)
        communication_context = self._communication_context(mapped=mapped, communication_fields=communication_fields)
        if communication_context:
            context_update["communication_context"] = communication_context
            context_update["communication_fields"] = communication_fields
        return ContextTransformResult(
            context_update=context_update,
            communication_context=communication_context,
            communication_fields=communication_fields,
            validation_summary={
                "input_context": "run_context",
                "mapped_field_count": len(mapped),
                "accepted": True,
                "validation_count": len(validations),
                "communication_field_count": len(communication_fields),
            },
        )

    def _map_row(
        self, *, row: dict[str, Any], field_mapping: Any, include_unmapped: bool
    ) -> dict[str, Any]:
        if not field_mapping:
            return dict(row)
        output: dict[str, Any] = dict(row) if include_unmapped else {}
        for entry in self._mapping_entries(field_mapping):
            value = self._mapped_value(container=row, entry=entry)
            output[entry["target"]] = entry["default"] if value is None and entry["default"] is not None else value
        return output

    def _mapping_entries(self, field_mapping: Any) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        if isinstance(field_mapping, dict):
            for target, rule in field_mapping.items():
                if isinstance(rule, dict):
                    entries.append(self._mapping_entry(target=target, rule=rule))
                else:
                    entries.append(self._mapping_entry(target=target, rule={"source": rule}))
        elif isinstance(field_mapping, list):
            for rule in field_mapping:
                if not isinstance(rule, dict):
                    continue
                target = str(rule.get("target") or rule.get("to") or "").strip()
                if target:
                    entries.append(self._mapping_entry(target=target, rule=rule))
        return entries

    def _mapping_entry(self, *, target: Any, rule: dict[str, Any]) -> dict[str, Any]:
        sources = rule.get("sources")
        if not isinstance(sources, list):
            sources = [rule.get("source") or rule.get("from") or target]
        source_paths = [str(source or "").strip() for source in sources if str(source or "").strip()]
        transform = str(rule.get("transform") or ("concat" if len(source_paths) > 1 else "copy")).strip().lower()
        if transform not in {"copy", "concat", "template"}:
            transform = "copy"
        return {
            "target": str(target or "").strip(),
            "source": source_paths[0] if source_paths else str(target or "").strip(),
            "sources": source_paths,
            "default": rule.get("default"),
            "transform": transform,
            "separator": str(rule.get("separator") if rule.get("separator") is not None else " "),
            "template": str(rule.get("template") or ""),
        }

    def _map_context(self, *, context: dict[str, Any], field_mapping: Any) -> dict[str, Any]:
        mapped: dict[str, Any] = {}
        for entry in self._mapping_entries(field_mapping):
            target_key = str(entry["target"] or "").strip()
            if not target_key:
                continue
            value = self._mapped_value(container=context, entry=entry)
            mapped[target_key] = entry["default"] if value is None and entry["default"] is not None else value
        return mapped

    def _mapped_value(self, *, container: dict[str, Any], entry: dict[str, Any]) -> Any:
        transform = str(entry.get("transform") or "copy").lower()
        if transform == "concat":
            values = [self._path_value(container, source) for source in entry.get("sources", [])]
            present = [str(value).strip() for value in values if not self._is_blank(value)]
            return str(entry.get("separator") or " ").join(present)
        if transform == "template":
            template = str(entry.get("template") or "")
            if template:
                return re.sub(
                    r"{{\s*([A-Za-z0-9_.-]+)\s*}}",
                    lambda match: "" if self._path_value(container, match.group(1)) is None else str(self._path_value(container, match.group(1))),
                    template,
                ).strip()
        return self._path_value(container, str(entry.get("source") or ""))

    def _communication_fields(self, *, config: dict[str, Any], mapped: dict[str, Any]) -> list[str]:
        configured = config.get("communication_fields") or config.get("template_fields") or []
        if isinstance(configured, list):
            fields = [str(field or "").strip() for field in configured if str(field or "").strip()]
        else:
            fields = []
        if bool(config.get("expose_all_mapped_to_templates")):
            fields.extend(mapped.keys())
        allowed = [
            field
            for field in fields
            if field in mapped and (field.startswith("intake.") or field.startswith("values."))
        ]
        return sorted(set(allowed))

    def _communication_context(self, *, mapped: dict[str, Any], communication_fields: list[str]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for field in communication_fields:
            value = mapped.get(field)
            if value is not None:
                self._set_path(output, field, value)
        return output

    def _nested_from_flat(self, values: dict[str, Any]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for path, value in values.items():
            self._set_path(output, path, value)
        return output

    @staticmethod
    def _set_path(output: dict[str, Any], path: str, value: Any) -> None:
        pieces = [piece for piece in str(path or "").split(".") if piece]
        if not pieces:
            return
        current = output
        for piece in pieces[:-1]:
            next_value = current.get(piece)
            if not isinstance(next_value, dict):
                next_value = {}
                current[piece] = next_value
            current = next_value
        current[pieces[-1]] = value

    def _validate_row(
        self, *, row: dict[str, Any], validations: list[Any]
    ) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        for validation in validations:
            if not isinstance(validation, dict):
                continue
            field = str(validation.get("field") or "").strip()
            if not field:
                continue
            value = self._path_value(row, field)
            rule = (
                str(
                    validation.get("rule")
                    or validation.get("validation")
                    or validation.get("type")
                    or "required"
                )
                .strip()
                .lower()
            )
            error = self._validate_value(
                field=field, value=value, rule=rule, validation=validation
            )
            if error:
                errors.append(error)
        return errors

    def _validate_value(
        self,
        *,
        field: str,
        value: Any,
        rule: str,
        validation: dict[str, Any],
    ) -> dict[str, Any] | None:
        if rule == "required" and self._is_blank(value):
            return {"field": field, "rule": "required", "message": "Value is required."}
        if rule in {
            "type",
            "string",
            "number",
            "integer",
            "boolean",
            "array",
            "object",
        }:
            expected = str(
                validation.get("expected")
                or validation.get("value")
                or validation.get("data_type")
                or rule
            ).lower()
            if expected == "type":
                expected = "string"
            if not self._matches_type(value, expected):
                return {
                    "field": field,
                    "rule": "type",
                    "expected": expected,
                    "message": f"Value must be {expected}.",
                }
        if rule == "enum":
            allowed = (
                validation.get("values")
                or validation.get("allowed")
                or validation.get("value")
                or []
            )
            allowed_values = allowed if isinstance(allowed, list) else [allowed]
            if value not in allowed_values:
                return {
                    "field": field,
                    "rule": "enum",
                    "allowed": allowed_values,
                    "message": "Value is not allowed.",
                }
        if rule == "regex":
            pattern = str(validation.get("pattern") or validation.get("value") or "")
            if pattern and re.search(pattern, str(value or "")) is None:
                return {
                    "field": field,
                    "rule": "regex",
                    "message": "Value does not match pattern.",
                }
        if rule in {"min", "max"}:
            threshold = validation.get("value")
            if not self._passes_numeric_bound(
                value=value, threshold=threshold, rule=rule
            ):
                return {
                    "field": field,
                    "rule": rule,
                    "value": threshold,
                    "message": f"Value failed {rule} check.",
                }
        if (
            rule == "date_parse"
            and value is not None
            and self._parse_date(value) is None
        ):
            return {
                "field": field,
                "rule": "date_parse",
                "message": "Value is not a parseable date.",
            }
        return None

    def _path_value(self, row: dict[str, Any], path: str) -> Any:
        current: Any = row
        for piece in str(path or "").split("."):
            if not piece:
                continue
            if not isinstance(current, dict) or piece not in current:
                return None
            current = current[piece]
        return current

    def _columns_from_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        keys: list[str] = []
        seen: set[str] = set()
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    keys.append(key)
        return [{"key": key, "label": key.replace("_", " ").title()} for key in keys]

    def _matches_type(self, value: Any, expected: str) -> bool:
        if value is None:
            return True
        if expected == "string":
            return isinstance(value, str)
        if expected == "number":
            return isinstance(value, int | float | Decimal) and not isinstance(
                value, bool
            )
        if expected == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected == "boolean":
            return isinstance(value, bool)
        if expected == "array":
            return isinstance(value, list)
        if expected == "object":
            return isinstance(value, dict)
        return True

    def _passes_numeric_bound(self, *, value: Any, threshold: Any, rule: str) -> bool:
        try:
            numeric_value = float(value)
            numeric_threshold = float(threshold)
        except (TypeError, ValueError):
            return False
        return (
            numeric_value >= numeric_threshold
            if rule == "min"
            else numeric_value <= numeric_threshold
        )

    def _parse_date(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    def _is_blank(self, value: Any) -> bool:
        return value is None or (isinstance(value, str) and not value.strip())
