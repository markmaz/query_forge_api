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

    def _map_row(
        self, *, row: dict[str, Any], field_mapping: Any, include_unmapped: bool
    ) -> dict[str, Any]:
        if not field_mapping:
            return dict(row)
        output: dict[str, Any] = dict(row) if include_unmapped else {}
        for target, source, default in self._mapping_entries(field_mapping):
            value = self._path_value(row, source)
            output[target] = default if value is None and default is not None else value
        return output

    def _mapping_entries(self, field_mapping: Any) -> list[tuple[str, str, Any]]:
        entries: list[tuple[str, str, Any]] = []
        if isinstance(field_mapping, dict):
            for target, rule in field_mapping.items():
                if isinstance(rule, dict):
                    entries.append(
                        (
                            str(target),
                            str(rule.get("source") or rule.get("from") or target),
                            rule.get("default"),
                        )
                    )
                else:
                    entries.append((str(target), str(rule), None))
        elif isinstance(field_mapping, list):
            for rule in field_mapping:
                if not isinstance(rule, dict):
                    continue
                target = str(rule.get("target") or rule.get("to") or "").strip()
                source = str(rule.get("source") or rule.get("from") or target).strip()
                if target:
                    entries.append((target, source, rule.get("default")))
        return entries

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
