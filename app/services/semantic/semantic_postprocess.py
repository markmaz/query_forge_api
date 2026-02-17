from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from app.services.semantic.semantic_llm_schema import normalize_concept_key

_UPPER_SNAKE_RE = re.compile(r"^[A-Z0-9]+(?:_[A-Z0-9]+)*$")
_YEAR_RE = re.compile(r"^\d{4}$")

_REASON_TOKEN_MAP = {
    "columnname_ends_with_id": "columnName ends with _id",
    "columnname_contains_code": "columnName contains code",
    "columnname_starts_with_k_": "columnName starts with k_",
    "samples_are_yyyy": "samples are YYYY",
    "description_indicates_descriptive_text": "description indicates descriptive text",
    "description_indicates_academic_year": "description indicates academic year",
}


def postprocess_semantic_proposal(card: Dict[str, Any], proposal: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    out = _with_defaults(proposal)
    notes: List[str] = []

    source = str(out.get("concept_source") or "fallback").strip().lower()
    if source not in {"canonical", "fallback"}:
        source = "fallback"
    out["concept_source"] = source
    out["canonical_match_confidence"] = clamp_confidence(out.get("canonical_match_confidence"))

    out["concept_key"] = normalize_concept_key(out.get("concept_key") or card.get("columnName") or "")

    reasons, reason_notes = validate_and_fix_reasons(card=card, reasons=out.get("reasons"))
    out["reasons"] = reasons
    notes.extend(reason_notes)

    out, override_notes = apply_deterministic_overrides(card=card, proposal=out)
    notes.extend(override_notes)

    out = enforce_identifier_semantics(out)
    out = enforce_time_geography(out, card)
    out["confidence"] = clamp_confidence(out.get("confidence"))

    out["concept_key"] = normalize_concept_key(out.get("concept_key") or card.get("columnName") or "")
    if not _UPPER_SNAKE_RE.match(out["concept_key"]):
        out["concept_key"] = normalize_concept_key(card.get("columnName") or "")

    out["reasons"] = _limit_reasons(out.get("reasons"), card)

    return out, _unique(notes)


def apply_deterministic_overrides(card: Dict[str, Any], proposal: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    out = dict(proposal)
    notes: List[str] = []

    column_name = str(card.get("columnName") or "").strip().lower()
    description = str(card.get("description") or "").strip().lower()
    samples = card.get("samples") if isinstance(card.get("samples"), list) else []

    identifier_match = (
        column_name.startswith("k_")
        or column_name.endswith("_key")
        or column_name.endswith("_id")
        or "_code" in column_name
    )

    if identifier_match:
        prev_type = str(out.get("semantic_type") or "").strip().lower()
        if prev_type != "identifier":
            notes.append("deterministic_override:identifier")
        out["semantic_type"] = "identifier"
        out["is_identifier"] = True
        out["aggregation_allowed"] = False
        out["group_by_allowed"] = True

        if "_code" in column_name:
            if any(token in description for token in ("standardized code", "assigned code", "identifier")):
                out["confidence"] = max(clamp_confidence(out.get("confidence")), 0.7)
            else:
                out["confidence"] = max(clamp_confidence(out.get("confidence")), 0.6)

    if "school_year" in column_name or _samples_are_yyyy(samples):
        prev_type = str(out.get("semantic_type") or "").strip().lower()
        if prev_type != "time" or str(out.get("sub_type") or "") != "time.year":
            notes.append("deterministic_override:time_year")
        out["semantic_type"] = "time"
        out["sub_type"] = "time.year"
        out["granularity_rank"] = 0
        out["aggregation_allowed"] = False
        if not _contains_reason(out.get("reasons"), "samples are YYYY") and _samples_are_yyyy(samples):
            out["reasons"] = _limit_reasons(list(out.get("reasons") or []) + ["samples are YYYY"], card)

    return out, notes


def deterministic_identifier_override(card: Dict[str, Any], proposal: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    return apply_deterministic_overrides(card=card, proposal=proposal)


def enforce_identifier_semantics(proposal: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(proposal)
    semantic_type = str(out.get("semantic_type") or "").strip().lower()
    if semantic_type == "identifier" or bool(out.get("is_identifier")):
        out["semantic_type"] = "identifier"
        out["is_identifier"] = True
        out["aggregation_allowed"] = False
        out["group_by_allowed"] = True
    return out


def enforce_time_geography(proposal: Dict[str, Any], card: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(proposal)
    semantic_type = str(out.get("semantic_type") or "").strip().lower()
    sub_type = str(out.get("sub_type") or "").strip() or None

    if semantic_type == "geography":
        if sub_type is None or not sub_type.startswith("geography."):
            out["sub_type"] = "geography.other"
            sub_type = out["sub_type"]
        out["granularity_rank"] = _geo_rank(sub_type)

    if semantic_type == "time":
        if sub_type is None or not sub_type.startswith("time."):
            samples = card.get("samples") if isinstance(card.get("samples"), list) else []
            out["sub_type"] = "time.year" if _samples_are_yyyy(samples) else "time.other"
            sub_type = out["sub_type"]
        out["granularity_rank"] = _time_rank(sub_type)

    return out


def validate_and_fix_reasons(card: Dict[str, Any], reasons: Any) -> Tuple[List[str], List[str]]:
    notes: List[str] = []

    if isinstance(reasons, str):
        reasons_list = [reasons]
    elif isinstance(reasons, list):
        reasons_list = reasons
    else:
        reasons_list = []

    column_name = str(card.get("columnName") or "").strip().lower()
    description = str(card.get("description") or "").strip().lower()
    samples = card.get("samples") if isinstance(card.get("samples"), list) else []

    fixed: List[str] = []
    for raw in reasons_list:
        if raw is None:
            continue
        text = str(raw).strip()
        if text == "":
            continue
        key = text.lower().replace("-", "_").replace(" ", "_")
        mapped = _REASON_TOKEN_MAP.get(key, text)
        low = mapped.lower()

        if "ends with _id" in low:
            if column_name.endswith("_id"):
                fixed.append("columnName ends with _id")
            else:
                notes.append("reason_rewritten:mismatch_ends_with_id")
            continue

        if "contains code" in low:
            if "code" in column_name:
                fixed.append("columnName contains code")
            else:
                notes.append("reason_rewritten:mismatch_contains_code")
            continue

        if "starts with k_" in low:
            if column_name.startswith("k_"):
                fixed.append("columnName starts with k_")
            else:
                notes.append("reason_rewritten:mismatch_starts_with_k")
            continue

        if "yyyy" in low:
            if _samples_are_yyyy(samples):
                fixed.append("samples are YYYY")
            else:
                notes.append("reason_rewritten:mismatch_yyyy")
            continue

        if "academic year" in low:
            if "school_year" in column_name or "academic year" in description:
                fixed.append("description indicates academic year")
            else:
                notes.append("reason_rewritten:mismatch_academic_year")
            continue

        fixed.append(_short_reason(text))

    if not fixed:
        if column_name.startswith("k_"):
            fixed = ["columnName starts with k_"]
        elif column_name.endswith("_id"):
            fixed = ["columnName ends with _id"]
        elif "code" in column_name:
            fixed = ["columnName contains code"]
        elif _samples_are_yyyy(samples):
            fixed = ["samples are YYYY"]
        elif description:
            fixed = ["description indicates descriptive text"]
        else:
            fixed = ["defaulted_due_to_uncertainty"]

    return _limit_reasons(fixed, card), _unique(notes)


def clamp_confidence(value: Any) -> float:
    try:
        out = float(value)
    except Exception:
        out = 0.5
    return max(0.0, min(1.0, out))


def _with_defaults(proposal: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(proposal or {})
    out.setdefault("concept_key", "")
    out.setdefault("concept_source", "fallback")
    out.setdefault("canonical_match_confidence", 0.0)
    out.setdefault("semantic_type", "attribute")
    out.setdefault("sub_type", None)
    out.setdefault("entity", None)
    out.setdefault("granularity_rank", 0)
    out.setdefault("filter_allowed", True)
    out.setdefault("group_by_allowed", True)
    out.setdefault("aggregation_allowed", False)
    out.setdefault("is_identifier", False)
    out.setdefault("is_metric", False)
    out.setdefault("display_priority", 0)
    out.setdefault("sensitive", False)
    out.setdefault("confidence", 0.5)
    out.setdefault("reasons", ["defaulted_due_to_uncertainty"])
    return out


def _contains_reason(reasons: Any, target: str) -> bool:
    if not isinstance(reasons, list):
        return False
    needle = target.strip().lower()
    for reason in reasons:
        if str(reason).strip().lower() == needle:
            return True
    return False


def _samples_are_yyyy(samples: List[Any]) -> bool:
    vals = [str(v).strip() for v in samples if v is not None and str(v).strip() != ""]
    if not vals:
        return False
    return all(bool(_YEAR_RE.match(v)) for v in vals)


def _geo_rank(sub_type: str) -> int:
    mapping = {
        "geography.zip": 0,
        "geography.city": 1,
        "geography.county": 2,
        "geography.state": 3,
        "geography.country": 4,
    }
    return int(mapping.get(sub_type, 0))


def _time_rank(sub_type: str) -> int:
    mapping = {
        "time.year": 0,
        "time.month": 1,
        "time.date": 2,
        "time.timestamp": 3,
    }
    return int(mapping.get(sub_type, 0))


def _short_reason(text: str) -> str:
    trimmed = " ".join(str(text).split())
    if len(trimmed) <= 100:
        return trimmed
    return trimmed[:100].rstrip()


def _limit_reasons(reasons: Any, card: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    if isinstance(reasons, str):
        reasons = [reasons]
    if isinstance(reasons, list):
        for reason in reasons:
            text = str(reason).strip()
            if not text:
                continue
            out.append(_short_reason(text))
    out = _unique(out)
    if not out:
        out = ["defaulted_due_to_uncertainty"]
    return out[:3]


def _unique(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out
