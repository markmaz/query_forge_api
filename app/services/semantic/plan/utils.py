from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

def _dedupe_text_values(values: Sequence[Any]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        if text == "":
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _first_nonempty(values: Sequence[Any]) -> Optional[str]:
    for raw in values:
        text = str(raw or "").strip()
        if text:
            return text
    return None


def is_grounded_value(value: str, spacy: Dict[str, Any], gazetteer_matches: Sequence[str]) -> bool:
    candidate = _normalize_grounded_text(value)
    if candidate == "":
        return False
    grounded_values: List[str] = []
    slots = spacy.get("slots") if isinstance(spacy.get("slots"), dict) else {}
    by_label = spacy.get("by_label") if isinstance(spacy.get("by_label"), dict) else {}
    ents = spacy.get("ents") if isinstance(spacy.get("ents"), list) else []
    for bucket in (
        list(slots.get("org_districts") or []),
        list(slots.get("org_schools") or []),
        list(by_label.get("ORG_DISTRICT") or []),
        list(by_label.get("ORG_SCHOOL") or []),
        list(gazetteer_matches or []),
    ):
        for raw in bucket:
            text = _normalize_grounded_text(raw)
            if text:
                grounded_values.append(text)
    for ent in ents:
        if not isinstance(ent, dict):
            continue
        label = str(ent.get("label") or "").strip().upper()
        if label not in {"ORG_DISTRICT", "ORG_SCHOOL"}:
            continue
        text = _normalize_grounded_text(ent.get("text"))
        if text:
            grounded_values.append(text)
    for grounded in grounded_values:
        if grounded == candidate:
            return True
        if grounded in candidate or candidate in grounded:
            return True
    return False


def _normalize_grounded_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text == "":
        return ""
    text = re.sub(r"[^\w\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _build_prompt_ngrams(prompt: str) -> List[str]:
    text = str(prompt or "").lower()
    text = re.sub(r"[^a-z0-9\\s]+", " ", text)
    tokens = [tok for tok in text.split() if tok]
    out: List[str] = []
    for n in (3, 2, 1):
        for idx in range(0, max(0, len(tokens) - n + 1)):
            out.append(" ".join(tokens[idx : idx + n]))
    return list(dict.fromkeys(out))


def _prompt_has_student_intent(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if text == "":
        return False
    return re.search(r"\b(student|students|kid|kids|pupil|pupils|learner|learners)\b", text) is not None


def _infer_intent_entity(prompt: str) -> Optional[str]:
    text = str(prompt or "").strip().lower()
    if text == "":
        return None
    if re.search(r"\b(student|students|kid|kids|pupil|pupils|learner|learners)\b", text):
        return "student"
    if re.search(r"\b(staff|teacher|teachers)\b", text):
        return "staff"
    if re.search(r"\b(parent|parents)\b", text):
        return "parent"
    return None


def _norm_entity(value: Any) -> Optional[str]:
    text = str(value or "").strip().lower()
    if text in {"student", "staff", "parent"}:
        return text
    return None


def _resolve_name_literal(*, prompt: str, extracted_values: Sequence[Dict[str, Any]]) -> Optional[str]:
    for item in extracted_values:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "").strip().lower() != "name":
            continue
        value = str(item.get("value") or "").strip()
        if value:
            return value
    text = str(prompt or "").strip()
    pattern = re.compile(r"\b(?:named|name\s+is|called)\s+([A-Za-z][A-Za-z'\-]*)", flags=re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return None
    value = str(match.group(1) or "").strip()
    return value or None


def _resolve_required_literal(*, prompt: str, extracted_values: Sequence[Dict[str, Any]]) -> Optional[str]:
    extracted = _resolve_name_literal(prompt=prompt, extracted_values=extracted_values)
    if extracted:
        return extracted
    tokens = re.findall(r"[A-Za-z][A-Za-z'\-]*", str(prompt or ""))
    subgroup_acronyms = {"EL", "ELL", "ESL", "LEP", "MLL", "IEP", "SPED"}
    for idx, token in enumerate(tokens):
        if idx == 0:
            continue
        if token.upper() in subgroup_acronyms:
            continue
        if token[:1].isupper():
            return token
    return None


def _resolve_school_literal(extracted_values: Sequence[Dict[str, Any]]) -> Optional[str]:
    for item in extracted_values:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "").strip().lower() != "school_name":
            continue
        value = str(item.get("value") or "").strip()
        if value:
            return value
    return None


def _prompt_requests_first_last_names(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if text == "":
        return False
    has_first = re.search(r"\bfirst\b", text) is not None
    has_last = re.search(r"\blast\b", text) is not None
    has_name = re.search(r"\bname\b|\bnames\b", text) is not None
    return has_first and has_last and has_name


def _requires_student_name_projection_with_school(
    *,
    prompt: str,
    intent_entity: Optional[str],
    school_literal: Optional[str],
) -> bool:
    return (
        str(intent_entity or "").strip().lower() == "student"
        and _prompt_requests_first_last_names(prompt)
        and bool(school_literal)
    )


def _has_student_first_last_projection(selected_columns: Sequence[Dict[str, Any]]) -> bool:
    keys = {
        str(item.get("concept_key") or "").strip().upper()
        for item in selected_columns
        if isinstance(item, dict)
    }
    has_first = bool(keys & {"STUDENT_FIRST_NAME", "FIRST_NAME"})
    has_last = bool(keys & {"STUDENT_LAST_NAME", "LAST_NAME"})
    return has_first and has_last


def _has_school_name_filter(*, filters: Sequence[Dict[str, Any]], school_literal: Optional[str]) -> bool:
    target = str(school_literal or "").strip().lower()
    if target == "":
        return False
    for item in filters:
        if not isinstance(item, dict):
            continue
        concept_key = str(item.get("concept_key") or "").strip().upper()
        if concept_key not in {"SCHOOL_NAME", "STUDENT_SCHOOL_NAME"}:
            continue
        value = str(item.get("value") or "").strip().lower()
        if target in value:
            return True
    return False


def _concept_entity_factor(
    *,
    intent_entity: str,
    concept_key: str,
    concept_entity: Optional[str],
    policy_service: Any = None,
) -> float:
    # Import inline to avoid circular deps at module level
    from app.services.domain.planner_concept_scoring_policy_service import PlannerConceptScoringPolicyService
    key = str(concept_key or "").strip().upper()
    entity = _norm_entity(concept_entity)
    service = policy_service or PlannerConceptScoringPolicyService(enable_db_lookup=False)
    factor = 1.0
    if entity == intent_entity:
        factor = service.resolve_factor(
            action_key="entity_exact_match_multiplier",
            context_tokens=["entity_exact_match"],
            default=1.4,
        )
    elif entity is not None and entity != intent_entity:
        factor = service.resolve_factor(
            action_key="entity_mismatch_multiplier",
            context_tokens=["entity_mismatch"],
            default=0.7,
        )
    if intent_entity == "student":
        if key in {"STUDENT_FIRST_NAME", "STUDENT_LAST_NAME", "STUDENT_MIDDLE_NAME"}:
            return max(
                factor,
                service.resolve_factor(
                    action_key="student_entity_name_exact_multiplier",
                    context_tokens=["intent_student", "student_entity_name_exact"],
                    default=1.6,
                ),
            )
        if key in {"FIRST_NAME", "LAST_NAME", "MIDDLE_NAME"}:
            return min(
                factor,
                service.resolve_factor(
                    action_key="student_entity_generic_name_multiplier",
                    context_tokens=["intent_student", "generic_name_concept"],
                    default=0.85,
                ),
            )
        if key.startswith("STAFF_") and "NAME" in key:
            return min(
                factor,
                service.resolve_factor(
                    action_key="student_cross_entity_name_multiplier",
                    context_tokens=["intent_student", "staff_name_concept"],
                    default=0.5,
                ),
            )
        if key.startswith("PARENT_") and "NAME" in key:
            return min(
                factor,
                service.resolve_factor(
                    action_key="student_cross_entity_name_multiplier",
                    context_tokens=["intent_student", "parent_name_concept"],
                    default=0.5,
                ),
            )
    return factor


def _filters_contain_literal(*, filters: Sequence[Dict[str, Any]], literal: str) -> bool:
    target = str(literal or "").strip().lower()
    if target == "":
        return False
    for item in filters:
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        if isinstance(value, str) and target in value.strip().lower():
            return True
        if isinstance(value, list):
            for element in value:
                if isinstance(element, str) and target in element.strip().lower():
                    return True
    return False


def _candidate_by_mid(candidate_columns: Sequence[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for row in candidate_columns:
        if not isinstance(row, dict):
            continue
        mid = _to_int(row.get("model_column_id"))
        if mid is None:
            continue
        out[mid] = dict(row)
    return out


def _candidate_by_concept(candidate_columns: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for row in candidate_columns:
        if not isinstance(row, dict):
            continue
        concept_key = str(row.get("concept_key") or "").strip().upper()
        if concept_key == "":
            continue
        out.setdefault(concept_key, []).append(dict(row))
    return out


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _trim(value: str, size: int) -> str:
    text = str(value or "").strip()
    if len(text) <= size:
        return text
    return text[:size].rstrip()


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _dict_get(payload: Any, *path: str) -> Any:
    current = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _in_clause(prefix: str, values: Sequence[str]) -> Tuple[str, Dict[str, Any]]:
    params: Dict[str, Any] = {}
    names: List[str] = []
    for idx, val in enumerate(values):
        key = f"{prefix}{idx}"
        names.append(f":{key}")
        params[key] = str(val)
    return ", ".join(names), params
