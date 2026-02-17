from __future__ import annotations

import re
from typing import Any, Dict, List

from app.config import SEMANTIC_AUTO_APPROVE_MAX_ERRORS, SEMANTIC_AUTO_APPROVE_THRESHOLD
from app.services.semantic.semantic_llm_schema import SemanticType, normalize_concept_key

_UPPER_SNAKE_RE = re.compile(r"^[A-Z0-9]+(?:_[A-Z0-9]+)*$")
_NUMERIC_SAMPLE_RE = re.compile(r"^-?\d+(\.\d+)?$")
_NUMERIC_TYPES = {"int", "integer", "bigint", "float", "double", "decimal", "numeric", "smallint", "tinyint"}


def validate_semantic_suggestion(
    *,
    output: Dict[str, Any],
    card: Dict[str, Any],
    auto_approve_threshold: float = SEMANTIC_AUTO_APPROVE_THRESHOLD,
    auto_approve_max_errors: int = SEMANTIC_AUTO_APPROVE_MAX_ERRORS,
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    data = dict(output)

    semantic_type = str(data.get("semantic_type") or "").strip()
    if semantic_type not in {t.value for t in SemanticType}:
        errors.append("invalid_semantic_type")

    confidence_raw = data.get("confidence", 0.0)
    try:
        confidence = float(confidence_raw)
    except Exception:
        confidence = 0.0
        errors.append("invalid_confidence")
    if confidence < 0.0 or confidence > 1.0:
        errors.append("invalid_confidence")
        confidence = max(0.0, min(1.0, confidence))

    raw_concept_key = str(data.get("concept_key") or "")
    if "." in raw_concept_key or "/" in raw_concept_key or any(ch.isspace() for ch in raw_concept_key):
        errors.append("concept_key_invalid_format")

    concept_key = normalize_concept_key(raw_concept_key)
    if concept_key == "":
        errors.append("empty_concept_key")
    if concept_key and not _UPPER_SNAKE_RE.match(concept_key):
        errors.append("concept_key_not_upper_snake")

    sub_type = data.get("sub_type")
    if sub_type is not None:
        sub_type = str(sub_type).strip() or None

    signals = data.get("signals")
    if not isinstance(signals, dict):
        signals = card.get("signals") if isinstance(card.get("signals"), dict) else {}

    contains_county_word = bool(signals.get("contains_county_word"))
    all_numeric = bool(signals.get("all_numeric"))
    boolean_like = bool(signals.get("boolean_like"))
    column_name = str(card.get("columnName") or "").strip().lower()

    reasons = _ensure_str_list(data.get("reasons"))
    for reason in reasons:
        low = reason.lower()
        if ("ends with _id" in low or "ends_with_id" in low) and not column_name.endswith("_id"):
            errors.append("reason_mismatch_endswith_id")
        if ("contains code" in low or "contains_code" in low) and "code" not in column_name:
            errors.append("reason_mismatch_contains_code")

    if semantic_type == "geography":
        if not sub_type:
            errors.append("geography_sub_type_required")
        elif sub_type == "geography.city" and contains_county_word:
            errors.append("geo_city_county_conflict")
        elif sub_type == "geography.county" and not contains_county_word:
            confidence = max(0.0, confidence - 0.1)

    if semantic_type == "time":
        if not sub_type or not str(sub_type).startswith("time."):
            errors.append("time_sub_type_invalid")

    is_metric = bool(data.get("is_metric")) or semantic_type == "metric"
    if is_metric:
        data_type = str(card.get("dataType") or card.get("data_type") or "").strip().lower()
        samples_raw = card.get("samples")
        samples: List[Any] = samples_raw if isinstance(samples_raw, list) else []
        has_samples = any(str(v).strip() != "" for v in samples if v is not None)
        numeric_type = _is_numeric_data_type(data_type)

        if not numeric_type and not all_numeric:
            if has_samples:
                non_numeric_found = any(
                    not _is_numeric_sample(v)
                    for v in samples
                    if v is not None and str(v).strip() != ""
                )
                if non_numeric_found:
                    errors.append("metric_sample_mismatch")
            else:
                warnings.append("metric_samples_missing")
                confidence = max(0.0, confidence - 0.05)

    is_identifier = bool(data.get("is_identifier"))
    group_by_allowed = bool(data.get("group_by_allowed", True))
    aggregation_allowed = bool(data.get("aggregation_allowed", True))
    if is_identifier:
        aggregation_allowed = False
        group_by_allowed = True

    if semantic_type == "flag" and not boolean_like:
        warnings.append("flag_sample_mismatch")

    is_valid = len(errors) == 0
    can_auto = (
        is_valid
        and confidence >= float(auto_approve_threshold)
        and len(errors) <= int(auto_approve_max_errors)
    )
    decision_status = "auto_approved" if can_auto else "pending"

    return {
        "concept_key": concept_key,
        "semantic_type": semantic_type,
        "sub_type": sub_type,
        "entity": _none_or_str(data.get("entity")),
        "granularity_rank": int(data.get("granularity_rank") or 0),
        "filter_allowed": bool(data.get("filter_allowed", True)),
        "group_by_allowed": group_by_allowed,
        "aggregation_allowed": aggregation_allowed,
        "is_identifier": is_identifier,
        "is_metric": is_metric,
        "display_priority": int(data.get("display_priority") or 0),
        "sensitive": bool(data.get("sensitive", False)),
        "confidence": confidence,
        "reasons": reasons,
        "warnings": warnings,
        "validation_errors": errors,
        "is_valid": is_valid,
        "decision_status": decision_status,
    }


def _none_or_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _ensure_str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(text)
    return out


def _is_numeric_data_type(value: str) -> bool:
    if value == "":
        return False
    compact = value.replace("(", " ").replace(")", " ").replace(",", " ").strip().lower()
    return any(token in compact for token in _NUMERIC_TYPES)


def _is_numeric_sample(value: Any) -> bool:
    text = str(value).strip()
    if text == "":
        return False
    return bool(_NUMERIC_SAMPLE_RE.match(text))
