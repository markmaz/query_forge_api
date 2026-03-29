"""Domain selection logic extracted from PlannerDomainService.

This module owns:
- Module-level pure helper functions used during domain selection.
- DomainSelectionService: encapsulates vector candidate retrieval, domain
  scoring, column shortlisting, and capabilities formatting for the LLM.

It intentionally does NOT import from app.services.planner_domain.service to
avoid a circular dependency.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from qdrant_client.http import models as qdrant_models

from app.config import (
    QF_PLAN_DOMAIN_FAST_MODE_MAX_DIMENSIONS,
    QF_PLAN_DOMAIN_FAST_MODE_MAX_FILTER_COLUMNS,
    QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED,
)
from app.exceptions.forge_error import ForgeError
from app.infra.embedding_model import EmbeddingModel
from app.infra.qdrant_client import QdrantClientWrapper
from app.services.domains.capabilities_service import DomainCapabilitiesService
from app.services.planner_domain.column_scoring import (
    _cap_columns_per_table,
    _column_heuristic_boost,
    _extract_group_entities_for_shortlist,
    _has_adm_metric,
    _has_adm_signal_columns,
    _has_age_columns,
    _has_birth_date_columns,
    _has_calendar_day_columns,
    _has_canonical_name_columns,
    _has_group_entity,
    _has_preferred_state_column,
    _has_school_day_flag_columns,
    _has_school_name_column,
    _has_staff_identity_column,
    _has_staff_role_title_column,
    _has_student_identity_column,
    _has_subgroup_column,
    _is_canonical_name_column_name,
    _is_name_column_needed_for_prompt,
    _is_preferred_name_column_name,
    _is_staff_classification_column_name,
    _is_staff_role_title_column_name,
    _is_state_school_code_name,
    _is_student_identity_column_name,
    _is_technical_school_key_name,
    _prompt_explicitly_requests_school_key,
    _prompt_prefers_human_school_name_filter,
    _prompt_prefers_staff_role_title_filter,
    _required_column_keys,
    _select_keys_with_table_cap,
)
from app.services.planner_domain.prompt_intents import (
    _dedupe_text_items,
    _extract_time_phrases,
    _looks_like_list_schools_prompt,
    _looks_like_list_students_prompt,
    _prompt_has_adm_intent,
    _prompt_has_age_extreme,
    _prompt_has_birth_month_constraint,
    _prompt_has_calendar_days_off,
    _prompt_has_city_state_pattern,
    _prompt_has_name_constraint,
    _prompt_has_nativity,
    _prompt_has_subgroup,
    _prompt_implies_staff_work_context,
    _prompt_implies_student_school_context,
    _prompt_mentions_school_or_district,
    _prompt_mentions_students,
    _prompt_prefers_canonical_name_columns,
    _slot_mentions_students,
)
from app.services.planner_domain.rerank_policy_engine import PlannerDomainRerankPolicyEngine
from app.services.planner.semantic_grounding_service import SemanticGroundingService

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_DISCIPLINE_HINT_RE = re.compile(
    r"\b(discipline|incident|suspension|expulsion|referral|behavior|behaviour)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Inline utility helpers (local copies to avoid circular import)
# ---------------------------------------------------------------------------


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower()


# ---------------------------------------------------------------------------
# Copied helper (also still in service.py for _semantic_value_alias_constraints)
# ---------------------------------------------------------------------------


def _dedupe_constraints(values: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for item in values:
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("kind") or "unknown").strip().lower() or "unknown"
        text = " ".join(str(item.get("text") or "").strip().split())
        op = str(item.get("op") or "unknown").strip().lower() or "unknown"
        value_hint = " ".join(str(item.get("value_hint") or "").strip().split()) if item.get("value_hint") not in (None, "") else ""
        notes = " ".join(str(item.get("notes") or "").strip().split()) if item.get("notes") not in (None, "") else ""
        if text == "" and value_hint == "":
            continue
        key = (kind, text.lower(), op, value_hint.lower(), notes.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "kind": kind,
                "text": text or value_hint,
                "op": op,
                "value_hint": value_hint or None,
                "notes": notes or None,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Moved module-level functions
# ---------------------------------------------------------------------------


def _semantic_alias_concept_key(constraint: Mapping[str, Any]) -> str:
    notes = str(constraint.get("notes") or "").strip()
    if ":" not in notes:
        return ""
    prefix, concept_key = notes.split(":", 1)
    if prefix.strip().lower() != "semantic_alias":
        return ""
    return str(concept_key or "").strip().upper()


def _replace_prompt_phrase(*, text: str, needle: str, replacement: str) -> str:
    base = str(text or "").strip()
    source = str(needle or "").strip()
    target = str(replacement or "").strip()
    if base == "" or source == "" or target == "":
        return base
    pattern = re.compile(rf"\b{re.escape(source)}\b", flags=re.IGNORECASE)
    rewritten = pattern.sub(target, base, count=1)
    return " ".join(rewritten.split())


def _merge_dimension_rows(*, dimensions: Sequence[Mapping[str, Any]], time_columns: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in list(dimensions) + list(time_columns):
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("column_key"))
        if key == "" or key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
    return out


def _build_column_query_texts(prompt: str) -> List[str]:
    text = str(prompt or "").strip()
    out = [text]
    text_l = text.lower()
    group_entities = _extract_group_entities_for_shortlist(text_l)
    if _has_group_entity(group_entities, "account"):
        out.extend(["account name", "customer account"])
    if _has_group_entity(group_entities, "territory"):
        out.extend(["territory name", "sales territory"])
    if _has_group_entity(group_entities, "region"):
        out.extend(["region name"])
    if _prompt_has_subgroup(text):
        out.extend(["student race ethnicity", "student subgroup"])
    if _looks_like_list_students_prompt(text):
        out.extend(["student list", "student roster", "student demographics"])
    if _prompt_has_age_extreme(text):
        out.extend(["student birth date", "student date of birth", "student age"])
    if _prompt_has_birth_month_constraint(text):
        out.extend(["student birthday month", "student birth date month"])
    if _prompt_implies_staff_work_context(text):
        out.extend(["staff roster", "staff assignments", "teacher workplace", "employee school"])
    if _prompt_prefers_staff_role_title_filter(text):
        out.extend(["staff position title", "staff role title", "principal position"])
    if _prompt_implies_student_school_context(text):
        out.extend(["student enrollment", "student attends school", "student school"])
    if "county" in text_l:
        out.append("county district")
    if "district" in text_l:
        out.append("district lea")
    if "school year" in text_l or "this year" in text_l or "last year" in text_l:
        out.append("school year date")
    if _prompt_has_adm_intent(text):
        out.extend(
            [
                "average daily membership adm base adm",
                "normalized_adm report_period school_year",
                "is_primary_school grade_level_adm",
            ]
        )
    return _dedupe_text_items(out)


def _build_domain_query_texts(prompt: str) -> List[str]:
    text = str(prompt or "").strip()
    if text == "":
        return []
    out = [text]
    text_l = text.lower()
    if _prompt_implies_staff_work_context(text):
        out.extend(["staff assignments", "staff workplace", "teacher employment", "employee roster"])
    if _prompt_implies_student_school_context(text):
        out.extend(["student enrollment", "student demographics", "student profile"])
    if _prompt_has_age_extreme(text):
        out.extend(["student demographics birth date age", "student profile date of birth"])
    if _prompt_has_birth_month_constraint(text):
        out.extend(["student demographics birth date birthday month", "student profile date of birth month"])
    if _DISCIPLINE_HINT_RE.search(text) is not None:
        out.extend(["discipline incidents", "student behavior"])
    if "district" in text_l or "lea" in text_l:
        out.append("school district lea")
    if _prompt_has_adm_intent(text):
        out.extend(
            [
                "average daily membership adm base adm",
                "student base adm attendance membership",
                "enrollment adm report period school year",
            ]
        )
    if _prompt_has_calendar_days_off(text):
        out.extend(
            [
                "academic calendar days off",
                "school calendar no school non instructional days",
                "calendar school day holiday schedule",
            ]
        )
    return _dedupe_text_items(out)


def _build_semantic_domain_query_specs(
    *,
    prompt: str,
    semantic_constraints: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    text = str(prompt or "").strip()
    if text == "":
        return []
    constraints = _dedupe_constraints(semantic_constraints)
    if not constraints:
        return []

    concept_keys = {
        key
        for key in (_semantic_alias_concept_key(item) for item in constraints)
        if key
    }
    specs: List[Dict[str, Any]] = []

    for constraint in constraints:
        raw_text = str(constraint.get("text") or "").strip()
        canonical = str(constraint.get("value_hint") or "").strip()
        if raw_text == "" or canonical == "" or raw_text.lower() == canonical.lower():
            continue
        rewritten_prompt = _replace_prompt_phrase(text=text, needle=raw_text, replacement=canonical)
        if rewritten_prompt and rewritten_prompt != text:
            concept_key = _semantic_alias_concept_key(constraint)
            reason = f"semantic_alias:{concept_key}" if concept_key else "semantic_alias"
            specs.append(
                {
                    "query": rewritten_prompt,
                    "score_boost": 0.02,
                    "reasons": [reason],
                    "source": "semantic_vector",
                }
            )

    if _prompt_has_nativity(text) or any("COUNTRY" in key for key in concept_keys):
        specs.extend(
            [
                {
                    "query": "student demographics birth country nativity",
                    "score_boost": 0.06,
                    "reasons": ["semantic_query:nativity"],
                    "source": "semantic_vector",
                },
                {
                    "query": "country of birth student profile demographics",
                    "score_boost": 0.04,
                    "reasons": ["semantic_query:nativity"],
                    "source": "semantic_vector",
                },
            ]
        )
    if _prompt_has_calendar_days_off(text) or any(
        any(token in key for token in ("SCHOOL_DAY", "INSTRUCTIONAL_DAY", "NON_INSTRUCTIONAL", "DAY_OFF", "HOLIDAY"))
        for key in concept_keys
    ):
        specs.extend(
            [
                {
                    "query": "academic calendar days off no school school day",
                    "score_boost": 0.08,
                    "reasons": ["semantic_query:calendar_days_off"],
                    "source": "semantic_vector",
                },
                {
                    "query": "non instructional days school calendar holiday schedule",
                    "score_boost": 0.06,
                    "reasons": ["semantic_query:calendar_days_off"],
                    "source": "semantic_vector",
                },
            ]
        )
    if any("SEMESTER" in key or "TERM" in key for key in concept_keys):
        specs.append(
            {
                "query": "academic calendar semester terms",
                "score_boost": 0.05,
                "reasons": ["semantic_query:semester"],
                "source": "semantic_vector",
            }
        )
    if any("SCHOOL_YEAR" in key or key.endswith("_YEAR") for key in concept_keys):
        specs.append(
            {
                "query": "school year academic calendar enrollment",
                "score_boost": 0.04,
                "reasons": ["semantic_query:school_year"],
                "source": "semantic_vector",
            }
        )
    if _prompt_has_subgroup(text):
        specs.append(
            {
                "query": "student subgroup demographics race ethnicity language",
                "score_boost": 0.04,
                "reasons": ["semantic_query:subgroup"],
                "source": "semantic_vector",
            }
        )
    return specs


def _build_domain_query_specs(
    *,
    prompt: str,
    semantic_constraints: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = [
        {
            "query": query_text,
            "score_boost": 0.0,
            "reasons": [],
            "source": "vector",
        }
        for query_text in _build_domain_query_texts(prompt)
    ]
    specs.extend(_build_semantic_domain_query_specs(prompt=prompt, semantic_constraints=semantic_constraints))

    merged: Dict[str, Dict[str, Any]] = {}
    for raw_spec in specs:
        query_text = " ".join(str(raw_spec.get("query") or "").strip().split())
        if query_text == "":
            continue
        key = query_text.lower()
        reasons = _dedupe_text_items(list(raw_spec.get("reasons") or []))
        score_boost = float(raw_spec.get("score_boost") or 0.0)
        source = str(raw_spec.get("source") or "vector")
        existing = merged.get(key)
        if existing is None:
            merged[key] = {
                "query": query_text,
                "score_boost": score_boost,
                "reasons": reasons,
                "source": source,
            }
            continue
        existing["score_boost"] = max(float(existing.get("score_boost") or 0.0), score_boost)
        existing["reasons"] = _dedupe_text_items(list(existing.get("reasons") or []) + reasons)
        if source != "vector":
            existing["source"] = source
    return list(merged.values())


def _domain_name_intent_bias(*, prompt: str, candidate: Mapping[str, Any]) -> float:
    name = str(candidate.get("name") or "").strip().lower()
    if name == "":
        return 0.0
    prompt_text = str(prompt or "").strip().lower()
    bias = 0.0

    if _prompt_implies_staff_work_context(prompt_text):
        if any(token in name for token in ("staff", "assignment", "employee", "teacher", "workforce")):
            bias += 0.18
        if "student" in name and _DISCIPLINE_HINT_RE.search(prompt_text) is None:
            bias -= 0.24
        if "discipline" in name and _DISCIPLINE_HINT_RE.search(prompt_text) is None:
            bias -= 0.28

    if _prompt_implies_student_school_context(prompt_text):
        if any(token in name for token in ("student", "demographic", "profile", "enrollment", "enrolment")):
            bias += 0.14
        if "discipline" in name and _DISCIPLINE_HINT_RE.search(prompt_text) is None:
            bias -= 0.12

    if _DISCIPLINE_HINT_RE.search(prompt_text) is not None and "discipline" in name:
        bias += 0.2

    if _prompt_has_adm_intent(prompt_text):
        if any(token in name for token in ("adm", "average daily membership", "membership", "enrollment", "attendance")):
            bias += 0.22
        if any(token in name for token in ("calendar", "academic time", "term", "semester")):
            bias -= 0.24

    if _prompt_has_age_extreme(prompt_text):
        if any(token in name for token in ("demographic", "profile", "student")):
            bias += 0.18
        if any(token in name for token in ("program", "service", "membership")):
            bias -= 0.16

    if _prompt_has_birth_month_constraint(prompt_text):
        if any(token in name for token in ("demographic", "profile", "student")):
            bias += 0.2
        if any(token in name for token in ("program", "service", "membership")):
            bias -= 0.18

    if _prompt_has_calendar_days_off(prompt_text):
        if any(token in name for token in ("calendar", "scheduling", "schedule", "term", "semester")):
            bias += 0.18

    return bias


def _slot_implies_student_listing(slot_hints: Optional[Mapping[str, Any]]) -> bool:
    if not isinstance(slot_hints, Mapping):
        return False
    intent = str(slot_hints.get("intent") or "").strip().lower()
    entity = str(slot_hints.get("entity") or "").strip().lower()
    return intent == "list" and entity in {"student", "students"}


def _slot_implies_school_listing(slot_hints: Optional[Mapping[str, Any]]) -> bool:
    if not isinstance(slot_hints, Mapping):
        return False
    intent = str(slot_hints.get("intent") or "").strip().lower()
    entity = str(slot_hints.get("entity") or "").strip().lower()
    return intent == "list" and entity in {"school", "schools"}


def _find_dimension_by_column_name(*, full_dims: Sequence[Mapping[str, Any]], target: str) -> Optional[Dict[str, Any]]:
    needle = str(target or "").strip().lower()
    if needle == "":
        return None
    for row in full_dims:
        col_name = str(row.get("column_name") or "").strip().lower()
        if col_name == needle:
            return dict(row)
    return None


def _find_dimension_by_column_name_candidates(
    *,
    full_dims: Sequence[Mapping[str, Any]],
    targets: Sequence[str],
) -> Optional[Dict[str, Any]]:
    normalized_targets = [str(target or "").strip().lower() for target in targets if str(target or "").strip()]
    if not normalized_targets:
        return None
    for target in normalized_targets:
        matched = _find_dimension_by_column_name(full_dims=full_dims, target=target)
        if matched is not None:
            return matched
    for row in full_dims:
        col_name = str(row.get("column_name") or "").strip().lower()
        if col_name == "":
            continue
        if any(target in col_name for target in normalized_targets):
            return dict(row)
    return None


def _prepend_student_identity_dimensions(
    *,
    selected_dims: Sequence[Mapping[str, Any]],
    full_dims: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    by_key: Dict[str, Dict[str, Any]] = {}
    for row in full_dims:
        key = _norm_key(row.get("column_key"))
        if key == "":
            continue
        by_key[key] = dict(row)

    identity_prefix: List[Dict[str, Any]] = []
    prefix_seen: set[str] = set()
    for target in ("student_unique_id", "first_name", "last_name"):
        matched = _find_dimension_by_column_name(full_dims=full_dims, target=target)
        if matched is None:
            continue
        key = _norm_key(matched.get("column_key"))
        if key == "" or key in prefix_seen:
            continue
        identity_prefix.append(dict(matched))
        prefix_seen.add(key)

    if not identity_prefix:
        return [dict(row) for row in selected_dims if isinstance(row, Mapping)]

    out: List[Dict[str, Any]] = list(identity_prefix)
    for row in selected_dims:
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("column_key"))
        if key == "" or key in prefix_seen:
            continue
        base = by_key.get(key) or dict(row)
        out.append(dict(base))
        prefix_seen.add(key)
    return out


def _prepend_school_listing_dimensions(
    *,
    selected_dims: Sequence[Mapping[str, Any]],
    full_dims: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    by_key: Dict[str, Dict[str, Any]] = {}
    for row in full_dims:
        key = _norm_key(row.get("column_key"))
        if key == "":
            continue
        by_key[key] = dict(row)

    school_prefix: List[Dict[str, Any]] = []
    prefix_seen: set[str] = set()
    for candidates in (
        ("school_name",),
        ("lea_name", "district_name", "district"),
        ("school_number", "school_num", "school_no"),
    ):
        matched = _find_dimension_by_column_name_candidates(full_dims=full_dims, targets=candidates)
        if matched is None:
            continue
        key = _norm_key(matched.get("column_key"))
        if key == "" or key in prefix_seen:
            continue
        school_prefix.append(dict(matched))
        prefix_seen.add(key)

    if not school_prefix:
        return [dict(row) for row in selected_dims if isinstance(row, Mapping)]

    out: List[Dict[str, Any]] = list(school_prefix)
    for row in selected_dims:
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("column_key"))
        if key == "" or key in prefix_seen:
            continue
        base = by_key.get(key) or dict(row)
        out.append(dict(base))
        prefix_seen.add(key)
    return out


def _prepend_school_name_for_filter_context(
    *,
    selected_dims: Sequence[Mapping[str, Any]],
    full_dims: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    school_name = _find_dimension_by_column_name(full_dims=full_dims, target="school_name")
    if school_name is None:
        return [dict(row) for row in selected_dims if isinstance(row, Mapping)]

    school_key = _norm_key(school_name.get("column_key"))
    out: List[Dict[str, Any]] = [dict(school_name)]
    seen: set[str] = {school_key}

    by_key: Dict[str, Dict[str, Any]] = {}
    for row in full_dims:
        key = _norm_key(row.get("column_key"))
        if key:
            by_key[key] = dict(row)

    for row in selected_dims:
        if not isinstance(row, Mapping):
            continue
        key = _norm_key(row.get("column_key"))
        if key == "" or key in seen:
            continue
        out.append(dict(by_key.get(key) or dict(row)))
        seen.add(key)
    return out


# ---------------------------------------------------------------------------
# DomainSelectionService
# ---------------------------------------------------------------------------


class DomainSelectionService:
    """Encapsulates domain candidate retrieval, scoring, and column shortlisting."""

    def __init__(
        self,
        *,
        domain_vector: Any,
        capabilities_service: DomainCapabilitiesService,
        rerank_policy_engine: PlannerDomainRerankPolicyEngine,
        embedding_model_factory: Callable[[], EmbeddingModel],
        column_vector_factory: Callable[[], QdrantClientWrapper],
        semantic_grounding_factory: Callable[[], SemanticGroundingService],
        semantic_alias_constraints_fn: Callable[..., List[Dict[str, Any]]],
    ) -> None:
        self._domain_vector = domain_vector
        self._capabilities = capabilities_service
        self._rerank_policy_engine = rerank_policy_engine
        self._embedding_model_factory = embedding_model_factory
        self._column_vector_factory = column_vector_factory
        self._semantic_grounding_factory = semantic_grounding_factory
        self._semantic_alias_constraints_fn = semantic_alias_constraints_fn

    def select_domain_and_shortlist(
        self,
        *,
        workspace_id: str,
        user_id: str,
        vertical_norm: str,
        prompt: str,
        provided_domain_id: Optional[int],
    ) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        """Public entry point combining candidate retrieval and domain selection.

        Returns a 6-tuple:
            (domain_candidates, selected_domain_id, capabilities,
             shortlisted_columns, ranking_debug, rerank_signals)
        """
        domain_candidates = self._get_domain_candidates(
            workspace_id=workspace_id,
            vertical_norm=vertical_norm,
            prompt=prompt,
            provided_domain_id=provided_domain_id,
        )
        selected_domain_id, capabilities, shortlisted_columns, ranking_debug, rerank_signals = (
            self._select_domain_and_shortlist_columns(
                workspace_id=workspace_id,
                user_id=user_id,
                vertical_norm=vertical_norm,
                prompt=prompt,
                domain_candidates=domain_candidates,
            )
        )
        return (
            domain_candidates,
            selected_domain_id,
            capabilities,
            shortlisted_columns,
            ranking_debug,
            rerank_signals,
        )

    @staticmethod
    def compact_capabilities_for_llm(
        capabilities: Mapping[str, Any],
        shortlisted_columns: Sequence[Mapping[str, Any]],
        prompt: str,
        slot_hints: Optional[Mapping[str, Any]] = None,
        fast_mode: bool = False,
    ) -> Dict[str, Any]:
        full_dims = [dict(row) for row in list(capabilities.get("dimensions") or []) if isinstance(row, dict)]
        full_time = [dict(row) for row in list(capabilities.get("time_columns") or []) if isinstance(row, dict)]
        full_filter_candidates = _merge_dimension_rows(dimensions=full_dims, time_columns=full_time)
        dim_by_key = {_norm_key(row.get("column_key")): row for row in full_dims if _norm_key(row.get("column_key"))}
        is_school_listing = _looks_like_list_schools_prompt(prompt) or _slot_implies_school_listing(slot_hints)
        prompt_mentions_students = _prompt_mentions_students(prompt) or _slot_mentions_students(slot_hints)
        prompt_mentions_school_district = _prompt_mentions_school_or_district(prompt)
        city_state_pattern = _prompt_has_city_state_pattern(prompt)
        has_preferred_state = _has_preferred_state_column(rows=full_dims)
        prefer_human_school_filter = (
            _prompt_prefers_human_school_name_filter(prompt)
            and _has_school_name_column(rows=full_filter_candidates)
            and not _prompt_explicitly_requests_school_key(prompt)
        )
        prefer_staff_role_title_filter = (
            _prompt_prefers_staff_role_title_filter(prompt)
            and _has_staff_role_title_column(rows=full_filter_candidates)
        )
        prefer_canonical_name_columns = (
            _prompt_prefers_canonical_name_columns(prompt)
            and _has_canonical_name_columns(rows=full_filter_candidates)
        )

        selected_dims: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for row in shortlisted_columns:
            key = _norm_key(row.get("column_key"))
            if key == "" or key in seen:
                continue
            base = dim_by_key.get(key) or dict(row)
            selected_dims.append(base)
            seen.add(key)

        if not selected_dims:
            selected_dims = full_dims[:40]
            seen = {_norm_key(row.get("column_key")) for row in selected_dims if _norm_key(row.get("column_key"))}

        if _prompt_has_subgroup(prompt):
            for row in full_dims:
                key = _norm_key(row.get("column_key"))
                if key in seen:
                    continue
                col_name = str(row.get("column_name") or key).lower()
                if any(token in col_name for token in ("race", "ethnicity", "hispanic", "latino")):
                    selected_dims.append(row)
                    seen.add(key)

        if prompt_mentions_students:
            selected_dims = _prepend_student_identity_dimensions(selected_dims=selected_dims, full_dims=full_dims)
            seen = {_norm_key(row.get("column_key")) for row in selected_dims if _norm_key(row.get("column_key"))}
            for row in full_dims:
                key = _norm_key(row.get("column_key"))
                if key in seen:
                    continue
                col_name = str(row.get("column_name") or key).lower()
                if _is_student_identity_column_name(col_name):
                    selected_dims.append(row)
                    seen.add(key)
                    if len(selected_dims) >= 55:
                        break
        if prompt_mentions_school_district:
            lea_dim = _find_dimension_by_column_name_candidates(
                full_dims=full_dims,
                targets=("lea_name", "district_name", "district"),
            )
            if lea_dim is not None:
                lea_key = _norm_key(lea_dim.get("column_key"))
                if lea_key and lea_key not in seen:
                    selected_dims.append(dict(lea_dim))
                    seen.add(lea_key)
        if is_school_listing:
            selected_dims = _prepend_school_listing_dimensions(selected_dims=selected_dims, full_dims=full_dims)
            seen = {_norm_key(row.get("column_key")) for row in selected_dims if _norm_key(row.get("column_key"))}
            if city_state_pattern and has_preferred_state:
                selected_dims = [
                    dict(row)
                    for row in selected_dims
                    if not _is_state_school_code_name(str(row.get("column_name") or "").strip().lower())
                ]
                seen = {_norm_key(row.get("column_key")) for row in selected_dims if _norm_key(row.get("column_key"))}
            if prefer_human_school_filter:
                selected_dims = [
                    dict(row)
                    for row in selected_dims
                    if not _is_technical_school_key_name(str(row.get("column_name") or "").strip().lower())
                ]
                seen = {_norm_key(row.get("column_key")) for row in selected_dims if _norm_key(row.get("column_key"))}
            for row in full_dims:
                key = _norm_key(row.get("column_key"))
                if key in seen:
                    continue
                col_name = str(row.get("column_name") or key).lower()
                if city_state_pattern and has_preferred_state and _is_state_school_code_name(col_name):
                    continue
                if prefer_human_school_filter and _is_technical_school_key_name(col_name):
                    continue
                if any(token in col_name for token in ("school_name", "lea_name", "school_number", "city", "state")):
                    selected_dims.append(row)
                    seen.add(key)
                    if len(selected_dims) >= 55:
                        break
        if prefer_human_school_filter:
            seen = {_norm_key(row.get("column_key")) for row in selected_dims if _norm_key(row.get("column_key"))}
            for row in full_dims:
                key = _norm_key(row.get("column_key"))
                if key in seen:
                    continue
                col_name = str(row.get("column_name") or key).lower()
                if _is_technical_school_key_name(col_name):
                    continue
                if col_name in {"school_name", "lea_name"}:
                    selected_dims.append(row)
                    seen.add(key)
            if selected_dims:
                selected_dims = _prepend_school_name_for_filter_context(selected_dims=selected_dims, full_dims=full_dims)

        if prefer_staff_role_title_filter:
            selected_dims = [
                dict(row)
                for row in selected_dims
                if not _is_staff_classification_column_name(str(row.get("column_name") or "").strip().lower())
            ]
            seen = {_norm_key(row.get("column_key")) for row in selected_dims if _norm_key(row.get("column_key"))}
            for row in full_dims:
                key = _norm_key(row.get("column_key"))
                if key in seen:
                    continue
                col_name = str(row.get("column_name") or key).lower()
                if _is_staff_role_title_column_name(col_name):
                    selected_dims.append(row)
                    seen.add(key)

        if prefer_canonical_name_columns:
            selected_dims = [
                dict(row)
                for row in selected_dims
                if not _is_preferred_name_column_name(str(row.get("column_name") or "").strip().lower())
            ]
            seen = {_norm_key(row.get("column_key")) for row in selected_dims if _norm_key(row.get("column_key"))}
            for row in full_dims:
                key = _norm_key(row.get("column_key"))
                if key in seen:
                    continue
                col_name = str(row.get("column_name") or key).lower()
                if _is_canonical_name_column_name(col_name):
                    selected_dims.append(row)
                    seen.add(key)

        if _prompt_has_name_constraint(prompt):
            for row in full_dims:
                key = _norm_key(row.get("column_key"))
                if key in seen:
                    continue
                col_name = str(row.get("column_name") or key).lower()
                if _is_name_column_needed_for_prompt(prompt=prompt, column_name=col_name):
                    selected_dims.append(row)
                    seen.add(key)

        max_columns = max(12, int(QF_PLAN_DOMAIN_FAST_MODE_MAX_DIMENSIONS)) if fast_mode else 70
        per_table_cap = 8 if fast_mode else 14
        selected_dims = _cap_columns_per_table(selected_dims, max_columns=max_columns, per_table_cap=per_table_cap)
        selected_time = [dict(row) for row in full_time[: (8 if fast_mode else 12)]]

        filter_columns: List[Dict[str, Any]] = []
        filter_seen: set[str] = set()

        def _add_filter_row(row: Mapping[str, Any]) -> None:
            key = _norm_key(row.get("column_key"))
            if key == "" or key in filter_seen:
                return
            if row.get("filterable") is False:
                return
            col_name = str(row.get("column_name") or "").strip().lower()
            if prefer_human_school_filter and _is_technical_school_key_name(col_name):
                return
            if prefer_staff_role_title_filter and _is_staff_classification_column_name(col_name):
                return
            if prefer_canonical_name_columns and _is_preferred_name_column_name(col_name):
                return
            filter_columns.append(dict(row))
            filter_seen.add(key)

        for row in selected_dims:
            _add_filter_row(row)
        for row in selected_time:
            _add_filter_row(row)

        if _prompt_has_nativity(prompt):
            nativity_names = {"birth_country", "country_of_birth", "date_entered_us"}
            for row in full_filter_candidates:
                col_name = str(row.get("column_name") or "").strip().lower()
                if col_name in nativity_names:
                    _add_filter_row(row)

        if _prompt_has_name_constraint(prompt):
            for row in full_filter_candidates:
                col_name = str(row.get("column_name") or "").strip().lower()
                if _is_name_column_needed_for_prompt(prompt=prompt, column_name=col_name):
                    _add_filter_row(row)

        max_filter_columns = max(12, int(QF_PLAN_DOMAIN_FAST_MODE_MAX_FILTER_COLUMNS)) if fast_mode else len(filter_columns)
        if len(filter_columns) > max_filter_columns:
            filter_columns = filter_columns[:max_filter_columns]

        return {
            "domain_id": _to_int(capabilities.get("domain_id")) or 0,
            "domain_version": _to_int(capabilities.get("domain_version")) or 0,
            "dimensions": selected_dims,
            "time_columns": selected_time,
            "filter_columns": filter_columns,
            "domain_metrics": [dict(row) for row in list(capabilities.get("domain_metrics") or []) if isinstance(row, dict)],
            "user_metrics": [dict(row) for row in list(capabilities.get("user_metrics") or []) if isinstance(row, dict)],
            "overlay_metrics": [dict(row) for row in list(capabilities.get("overlay_metrics") or []) if isinstance(row, dict)],
        }

    @staticmethod
    def full_capabilities_for_execution(capabilities: Mapping[str, Any]) -> Dict[str, Any]:
        dimensions = [dict(row) for row in list(capabilities.get("dimensions") or []) if isinstance(row, dict)]
        time_columns = [dict(row) for row in list(capabilities.get("time_columns") or []) if isinstance(row, dict)]
        filter_columns = [
            dict(row)
            for row in _merge_dimension_rows(dimensions=dimensions, time_columns=time_columns)
            if row.get("filterable") is not False
        ]
        return {
            "domain_id": _to_int(capabilities.get("domain_id")) or 0,
            "domain_version": _to_int(capabilities.get("domain_version")) or 0,
            "dimensions": dimensions,
            "time_columns": time_columns,
            "filter_columns": filter_columns,
            "domain_metrics": [dict(row) for row in list(capabilities.get("domain_metrics") or []) if isinstance(row, dict)],
            "user_metrics": [dict(row) for row in list(capabilities.get("user_metrics") or []) if isinstance(row, dict)],
            "overlay_metrics": [dict(row) for row in list(capabilities.get("overlay_metrics") or []) if isinstance(row, dict)],
        }

    @staticmethod
    def _score_domain_candidate(
        prompt: str,
        candidate: Mapping[str, Any],
        capabilities: Mapping[str, Any],
        shortlisted_columns: Sequence[Mapping[str, Any]],
    ) -> float:
        vector_score = max(0.0, float(candidate.get("score") or 0.0))
        dimension_count = max(1, len(list(capabilities.get("dimensions") or [])))
        shortlist_ratio = min(1.0, len(list(shortlisted_columns)) / float(min(70, dimension_count)))
        score = (vector_score * 0.65) + (shortlist_ratio * 0.35)

        if _prompt_has_subgroup(prompt) and _has_subgroup_column(shortlisted_columns):
            score += 0.15
        if _looks_like_list_students_prompt(prompt) and _has_student_identity_column(shortlisted_columns):
            score += 0.08
        if _prompt_implies_staff_work_context(prompt) and _has_staff_identity_column(shortlisted_columns):
            score += 0.14
        if _prompt_implies_student_school_context(prompt) and _has_student_identity_column(shortlisted_columns):
            score += 0.12
        if _prompt_has_adm_intent(prompt):
            if _has_adm_signal_columns(shortlisted_columns):
                score += 0.2
            if _has_adm_metric(capabilities):
                score += 0.12
        if _prompt_has_age_extreme(prompt):
            if _has_birth_date_columns(shortlisted_columns):
                score += 0.2
            if _has_age_columns(shortlisted_columns):
                score += 0.16
        if _prompt_has_birth_month_constraint(prompt):
            if _has_birth_date_columns(shortlisted_columns):
                score += 0.24
        if _prompt_has_calendar_days_off(prompt):
            if _has_calendar_day_columns(shortlisted_columns):
                score += 0.16
            if _has_school_day_flag_columns(shortlisted_columns):
                score += 0.18
        score += _domain_name_intent_bias(prompt=prompt, candidate=candidate)
        if len(shortlisted_columns) < 5:
            score -= 0.1
        return round(score, 5)

    @staticmethod
    def _score_semantic_grounding_bundle(
        prompt: str,
        grounding_bundle: Any,
    ) -> float:
        candidates = getattr(grounding_bundle, "candidates", None)
        alias_constraints = list(getattr(grounding_bundle, "alias_constraints", []) or [])
        if candidates is None:
            return 0.02 if alias_constraints else 0.0

        score = 0.0
        metric_count = len(list(getattr(candidates, "metric_candidates", []) or []))
        dimension_count = len(list(getattr(candidates, "dimension_candidates", []) or []))
        filter_count = len(list(getattr(candidates, "filter_candidates", []) or []))
        time_count = len(list(getattr(candidates, "time_candidates", []) or []))

        if metric_count > 0:
            score += 0.06
        if dimension_count > 0:
            score += 0.05
        if filter_count > 0:
            score += 0.04
        if time_count > 0 and _extract_time_phrases(prompt):
            score += 0.03
        if alias_constraints:
            score += min(0.04, 0.02 * len(alias_constraints))

        metadata = dict(getattr(candidates, "metadata", {}) or {})
        if metadata.get("semantic_source") not in {None, "", "fallback_capabilities"}:
            score += 0.02

        return round(min(0.22, score), 5)

    def _get_domain_candidates(
        self,
        *,
        workspace_id: str,
        vertical_norm: str,
        prompt: str,
        provided_domain_id: Optional[int],
    ) -> List[Dict[str, Any]]:
        provided = _to_int(provided_domain_id)
        if provided is not None and provided > 0:
            return [{"domain_id": provided, "name": f"domain_{provided}", "score": 1.0, "source": "provided"}]

        semantic_constraints = self._semantic_alias_constraints_fn(prompt=prompt, vertical_norm=vertical_norm)
        query_specs = _build_domain_query_specs(
            prompt=prompt,
            semantic_constraints=semantic_constraints,
        )
        rows: List[Dict[str, Any]] = []
        for query_spec in query_specs:
            query_text = str(query_spec.get("query") or "").strip()
            if query_text == "":
                continue
            result = self._domain_vector.search_domains(
                workspace_id=workspace_id,
                query=query_text,
                limit=6,
                score_threshold=0.0,
                include_payload=False,
            )
            semantic_boost = float(query_spec.get("score_boost") or 0.0)
            semantic_reasons = list(query_spec.get("reasons") or [])
            query_source = str(query_spec.get("source") or "vector")
            for row in list(result.get("results") or []):
                if not isinstance(row, dict):
                    continue
                merged_row = dict(row)
                merged_row["_semantic_boost"] = semantic_boost
                merged_row["_semantic_reasons"] = semantic_reasons
                merged_row["_query_source"] = query_source
                rows.append(merged_row)
        out: List[Dict[str, Any]] = []
        by_domain: Dict[int, Dict[str, Any]] = {}
        seen: set[int] = set()
        for row in rows:
            domain_id = _to_int(row.get("domain_id"))
            if domain_id is None:
                continue
            current_score = float(row.get("score") or 0.0) + float(row.get("_semantic_boost") or 0.0)
            query_reasons = _dedupe_text_items(
                [
                    *list(row.get("reason") or []),
                    *list(row.get("_semantic_reasons") or []),
                ]
            )
            query_source = str(row.get("_query_source") or "vector")
            existing = by_domain.get(domain_id)
            if existing is None:
                by_domain[domain_id] = {
                    "domain_id": domain_id,
                    "name": str(row.get("name") or f"domain_{domain_id}"),
                    "score": current_score,
                    "reason": query_reasons,
                    "source": query_source,
                }
                continue
            existing_reasons = list(existing.get("reason") or [])
            new_reasons = query_reasons
            existing["reason"] = _dedupe_text_items(existing_reasons + new_reasons)
            if current_score > float(existing.get("score") or 0.0):
                existing["score"] = current_score
                existing["name"] = str(row.get("name") or existing.get("name") or f"domain_{domain_id}")
                existing["source"] = query_source
        for domain_id, row in by_domain.items():
            if domain_id in seen:
                continue
            seen.add(domain_id)
            out.append(dict(row))
        out.sort(key=lambda item: (-float(item.get("score") or 0.0), int(item.get("domain_id") or 0)))
        out = out[:6]
        if not out:
            raise ForgeError("No candidate domain found for prompt", status_code=404)
        return out

    def _select_domain_and_shortlist_columns(
        self,
        *,
        workspace_id: str,
        user_id: str,
        vertical_norm: str,
        prompt: str,
        domain_candidates: Sequence[Mapping[str, Any]],
    ) -> Tuple[int, Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        ranking: List[Dict[str, Any]] = []
        best_row: Optional[Dict[str, Any]] = None
        first_error: Optional[ForgeError] = None
        prompt_signals = self._rerank_policy_engine.extract_prompt_signals(prompt=prompt)

        for candidate in list(domain_candidates or [])[:3]:
            domain_id = _to_int(candidate.get("domain_id"))
            if domain_id is None:
                continue
            try:
                capabilities = self._capabilities.get_domain_capabilities(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    domain_id=domain_id,
                    vertical_norm=vertical_norm,
                )
            except ForgeError as exc:
                if first_error is None:
                    first_error = exc
                ranking.append({"domain_id": domain_id, "status": "error", "error": str(exc), "score": 0.0})
                continue

            shortlist = self._shortlist_columns_for_domain(
                prompt=prompt,
                workspace_id=workspace_id,
                capabilities=capabilities,
            )
            semantic_score = 0.0
            if QF_PLAN_DOMAIN_SEMANTIC_ASSIST_ENABLED:
                semantic_capabilities = self.compact_capabilities_for_llm(
                    capabilities,
                    shortlist,
                    prompt,
                    slot_hints=None,
                    fast_mode=False,
                )
                grounding_bundle = self._semantic_grounding_factory().build_grounding_bundle(
                    prompt=prompt,
                    workspace_id=workspace_id,
                    vertical_norm=vertical_norm,
                    base_domain_id=int(domain_id),
                    base_domain_name=str(candidate.get("name") or f"domain_{domain_id}"),
                    capabilities_compact=semantic_capabilities,
                    include_candidates=True,
                    include_alias_constraints=True,
                )
                semantic_score = self._score_semantic_grounding_bundle(
                    prompt=prompt,
                    grounding_bundle=grounding_bundle,
                )
            score = self._score_domain_candidate(
                prompt=prompt,
                candidate=candidate,
                capabilities=capabilities,
                shortlisted_columns=shortlist,
            )
            base_score = round(score + semantic_score, 5)
            policy_eval = self._rerank_policy_engine.evaluate_candidate(
                prompt=prompt,
                workspace_id=workspace_id,
                vertical_norm=vertical_norm,
                base_domain_id=int(domain_id),
                base_score=base_score,
                capabilities=capabilities,
                shortlisted_columns=shortlist,
                prompt_signals=prompt_signals,
            )
            score = float(policy_eval["final_score"])
            row = {
                "domain_id": domain_id,
                "score": score,
                "base_score": base_score,
                "semantic_score": semantic_score,
                "vector_score": float(candidate.get("score") or 0.0),
                "policy_adjustment": float((policy_eval.get("rerank_summary") or {}).get("policy_adjustment") or 0.0),
                "rerank_signals": list(policy_eval.get("prompt_signals") or []),
                "domain_capabilities": dict(policy_eval.get("domain_capabilities") or {}),
                "policy_effects": list(policy_eval.get("policy_effects") or []),
                "rerank_summary": dict(policy_eval.get("rerank_summary") or {}),
                "column_shortlist_count": len(shortlist),
                "dimension_count": len(list(capabilities.get("dimensions") or [])),
                "source": str(candidate.get("source") or "vector"),
                "capabilities": capabilities,
                "shortlisted_columns": shortlist,
            }
            ranking.append({k: v for k, v in row.items() if k not in {"capabilities", "shortlisted_columns"}})
            if best_row is None or float(row["score"]) > float(best_row["score"]):
                best_row = row

        if best_row is None:
            if first_error is not None:
                raise first_error
            raise ForgeError("No accessible domain candidates found", status_code=404)

        return (
            int(best_row["domain_id"]),
            dict(best_row["capabilities"]),
            list(best_row["shortlisted_columns"]),
            ranking,
            prompt_signals,
        )

    def _shortlist_columns_for_domain(
        self,
        *,
        prompt: str,
        workspace_id: str,
        capabilities: Mapping[str, Any],
    ) -> List[Dict[str, Any]]:
        all_rows = _merge_dimension_rows(
            dimensions=list(capabilities.get("dimensions") or []),
            time_columns=list(capabilities.get("time_columns") or []),
        )
        if not all_rows:
            return []

        by_key = {_norm_key(row.get("column_key")): row for row in all_rows if _norm_key(row.get("column_key"))}
        table_ids = sorted(
            {
                int(wtid)
                for wtid in (_to_int(row.get("workspace_table_id")) for row in all_rows)
                if wtid is not None
            }
        )
        if not table_ids:
            return all_rows[:40]

        query_texts = _build_column_query_texts(prompt)
        try:
            vectors = self._embedding_model_factory().encode(query_texts, normalize=True)
        except Exception:
            return _cap_columns_per_table(all_rows, max_columns=50, per_table_cap=12)
        query_filter = qdrant_models.Filter(
            must=[
                qdrant_models.FieldCondition(
                    key="kind",
                    match=qdrant_models.MatchValue(value="column"),
                ),
                qdrant_models.FieldCondition(
                    key="workspace_id",
                    match=qdrant_models.MatchValue(value=str(workspace_id)),
                ),
                qdrant_models.FieldCondition(
                    key="workspace_table_id",
                    match=qdrant_models.MatchAny(any=table_ids),
                ),
            ]
        )

        by_score: Dict[str, float] = {}
        limit = min(max(len(all_rows), 80), 220)
        try:
            for vector in vectors:
                hits = self._column_vector_factory().search(
                    vector=vector,
                    limit=limit,
                    query_filter=query_filter,
                    with_payload=True,
                )
                for hit in hits:
                    payload = hit.payload or {}
                    wtid = _to_int(payload.get("workspace_table_id"))
                    col = str(payload.get("column_name") or "").strip().lower()
                    if wtid is None or col == "":
                        continue
                    key = f"wt{wtid}.{col}"
                    if key not in by_key:
                        continue
                    score = float(hit.score or 0.0)
                    if score > float(by_score.get(key) or 0.0):
                        by_score[key] = score
        except Exception:
            return _cap_columns_per_table(all_rows, max_columns=50, per_table_cap=12)

        if not by_score:
            return _cap_columns_per_table(all_rows, max_columns=50, per_table_cap=12)

        for key, row in by_key.items():
            score = float(by_score.get(key) or 0.0)
            by_score[key] = score + _column_heuristic_boost(prompt=prompt, row=row)

        required_keys = _required_column_keys(prompt=prompt, rows=all_rows)
        ordered = sorted(by_score.items(), key=lambda item: item[1], reverse=True)
        selected_keys = _select_keys_with_table_cap(
            ordered_keys=[key for key, _ in ordered],
            row_by_key=by_key,
            max_columns=min(max(35, len(required_keys) + 25), 70),
            per_table_cap=12,
        )
        for key in required_keys:
            if key not in selected_keys and key in by_key:
                selected_keys.append(key)
        selected_keys = selected_keys[:70]
        return [dict(by_key[key]) for key in selected_keys if key in by_key]
