# app/services/ai_suggest/edit_enforcer.py
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from app.models.query.ai_suggest import AddAggregateEdit, SuggestModelResponse, SqlColumnKey
from app.services.ai_suggest.edit_inspector import (
    _column_ref_identity,
    _expand_filter_literal_aliases,
    _is_grade_column_name,
    _to_grade_integer,
)

logger = logging.getLogger(__name__)


class EditEnforcer:
    """Post-normalization business rule enforcement on the edit list."""

    def enforce_grounding(
        self,
        *,
        validated: SuggestModelResponse,
        valid_domain_ids: Optional[set[int]],
        valid_column_keys: Optional[set[str]],
    ) -> Tuple[SuggestModelResponse, int]:
        allowed_domains = {int(v) for v in (valid_domain_ids or set())}
        allowed_columns = {str(v) for v in (valid_column_keys or set()) if str(v).strip()}
        enforce_domains = bool(allowed_domains)
        enforce_columns = bool(allowed_columns)
        if not enforce_domains and not enforce_columns:
            return validated, 0

        filtered = []
        removed = 0
        for edit in validated.edits:
            op = getattr(edit, "op", "")
            if op == "setDomain" and enforce_domains:
                if int(getattr(edit, "domainId")) not in allowed_domains:
                    removed += 1
                    continue
            elif op in {"addSelect", "addFilter", "addGroupBy", "addAggregate", "addSort"} and enforce_columns:
                col = getattr(edit, "col", None)
                column_signature = self._column_signature(col) if col is not None else ""
                if column_signature not in allowed_columns:
                    removed += 1
                    continue
            filtered.append(edit)

        if removed == 0:
            return validated, 0

        confidence_penalty = min(0.5, removed * 0.15)
        confidence = max(0.0, float(validated.confidence) - confidence_penalty)
        note = (
            f"{validated.explanation} "
            f"Note: removed {removed} edit(s) that were not grounded in retrieved candidates."
        ).strip()
        return SuggestModelResponse(edits=filtered, explanation=note, confidence=confidence), removed

    def normalize_distinct_aggregate(
        self,
        validated: SuggestModelResponse,
        *,
        distinct_requested: bool,
    ) -> Tuple[SuggestModelResponse, int]:
        if distinct_requested:
            return validated, 0

        normalized_count = 0
        normalized_edits: List[Any] = []
        for edit in validated.edits:
            if (
                getattr(edit, "op", "") == "addAggregate"
                and getattr(edit, "func", "") == "count_distinct"
            ):
                normalized_count += 1
                normalized_edits.append(
                    AddAggregateEdit(
                        op="addAggregate",
                        func="count",
                        col=getattr(edit, "col", None),
                        alias=getattr(edit, "alias", "count_result"),
                    )
                )
                continue
            normalized_edits.append(edit)

        if normalized_count == 0:
            return validated, 0
        return (
            SuggestModelResponse(
                edits=normalized_edits,
                explanation=validated.explanation,
                confidence=validated.confidence,
            ),
            normalized_count,
        )

    def normalize_geography_filter_aliases(
        self,
        validated: SuggestModelResponse,
    ) -> Tuple[SuggestModelResponse, int]:
        expanded_count = 0
        normalized_edits: List[Any] = []
        for edit in validated.edits:
            if getattr(edit, "op", "") != "addFilter":
                normalized_edits.append(edit)
                continue

            operator = getattr(edit, "operator", "")
            value = getattr(edit, "value", None)
            col_obj = getattr(edit, "col", None)
            col_name = getattr(col_obj, "columnName", "") if col_obj is not None else ""
            if _is_grade_column_name(col_name):
                if operator == "equals":
                    converted = _to_grade_integer(value)
                    if converted is not None and converted != value:
                        expanded_count += 1
                        normalized_edits.append(
                            type(edit)(
                                op="addFilter",
                                col=getattr(edit, "col"),
                                operator="equals",
                                value=converted,
                            )
                        )
                        continue
                if operator == "in" and isinstance(value, list):
                    converted_values: List[Any] = []
                    changed = False
                    for item in value:
                        converted = _to_grade_integer(item)
                        if converted is not None:
                            converted_values.append(converted)
                            if converted != item:
                                changed = True
                        else:
                            converted_values.append(item)
                    deduped_values: List[Any] = []
                    seen: set[str] = set()
                    for item in converted_values:
                        key = f"{type(item).__name__}:{item}"
                        if key in seen:
                            changed = True
                            continue
                        seen.add(key)
                        deduped_values.append(item)
                    if changed:
                        expanded_count += 1
                        normalized_edits.append(
                            type(edit)(
                                op="addFilter",
                                col=getattr(edit, "col"),
                                operator="in",
                                value=deduped_values,
                            )
                        )
                        continue

            if operator == "equals" and isinstance(value, str):
                expanded_values = _expand_filter_literal_aliases(value)
                if len(expanded_values) > 1:
                    expanded_count += 1
                    normalized_edits.append(
                        type(edit)(
                            op="addFilter",
                            col=getattr(edit, "col"),
                            operator="in",
                            value=expanded_values,
                        )
                    )
                    continue

            if operator == "in" and isinstance(value, list):
                merged: List[str] = []
                for item in value:
                    if isinstance(item, str):
                        merged.extend(_expand_filter_literal_aliases(item))
                    else:
                        merged.append(item)
                deduped: List[Any] = []
                seen2: set[str] = set()
                for item in merged:
                    if isinstance(item, str):
                        k = item.lower()
                        if k in seen2:
                            continue
                        seen2.add(k)
                    deduped.append(item)
                if deduped != value:
                    expanded_count += 1
                    normalized_edits.append(
                        type(edit)(
                            op="addFilter",
                            col=getattr(edit, "col"),
                            operator="in",
                            value=deduped,
                        )
                    )
                    continue

            normalized_edits.append(edit)

        if expanded_count == 0:
            return validated, 0
        return (
            SuggestModelResponse(
                edits=normalized_edits,
                explanation=validated.explanation,
                confidence=validated.confidence,
            ),
            expanded_count,
        )

    def order_setdomain_first(self, edits: List[Any]) -> List[Any]:
        set_domain_edits = [edit for edit in edits if getattr(edit, "op", "") == "setDomain"]
        if not set_domain_edits:
            return list(edits)
        non_domain_edits = [edit for edit in edits if getattr(edit, "op", "") != "setDomain"]
        return [*set_domain_edits, *non_domain_edits]

    def enforce_sqljson_aggs_from_edits(self, sqljson: Dict[str, Any], edits: list[dict]) -> None:
        group_by: List[Dict[str, Any]] = []
        seen: set[tuple] = set()
        for edit in edits:
            if not isinstance(edit, dict):
                continue
            if str(edit.get("op") or "") != "addGroupBy":
                continue
            col = edit.get("col")
            if not isinstance(col, dict):
                continue
            identity = _column_ref_identity(col)
            if identity in seen:
                continue
            seen.add(identity)
            group_by.append(dict(col))

        metrics: List[Dict[str, Any]] = []
        for edit in edits:
            if not isinstance(edit, dict):
                continue
            if str(edit.get("op") or "") != "addAggregate":
                continue
            metrics.append(
                {
                    "id": uuid4().hex,
                    "fn": edit.get("func"),
                    "field": dict(edit.get("col")) if isinstance(edit.get("col"), dict) else None,
                    "label": edit.get("alias"),
                }
            )

        if not metrics and not group_by:
            sqljson["aggs"] = None
            return

        sqljson["aggs"] = {
            "enabled": True,
            "metrics": metrics,
            "groupBy": group_by,
        }

    def enforce_sqljson_sorting_from_edits(self, sqljson: Dict[str, Any], edits: list[dict]) -> None:
        sorting: List[Dict[str, Any]] = []
        seen: set[tuple] = set()
        for edit in edits:
            if not isinstance(edit, dict):
                continue
            if str(edit.get("op") or "") != "addSort":
                continue
            col = edit.get("col")
            direction = str(edit.get("dir") or "").lower()
            if not isinstance(col, dict):
                continue
            if direction not in {"asc", "desc"}:
                continue
            identity = (_column_ref_identity(col), direction)
            if identity in seen:
                continue
            seen.add(identity)
            sorting.append({"col": dict(col), "dir": direction})

        sqljson["sorting"] = sorting

    def _column_signature(self, col: SqlColumnKey) -> str:
        return "|".join(
            [
                str(col.workspaceTableId),
                (col.columnName or "").strip().lower(),
            ]
        )
