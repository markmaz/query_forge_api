"""Column scoring and selection heuristics for the planner domain service.

Pure functions that decide which columns to surface or suppress based on
prompt signals.  No I/O, no external dependencies beyond prompt_intents.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.services.planner_domain.prompt_intents import (
    _dedupe_text_items,
    _looks_like_list_students_prompt,
    _prompt_explicitly_requests_preferred_name,
    _prompt_has_adm_intent,
    _prompt_has_age_extreme,
    _prompt_has_birth_month_constraint,
    _prompt_has_calendar_days_off,
    _prompt_has_city_state_pattern,
    _prompt_has_subgroup,
    _prompt_prefers_canonical_name_columns,
)

# ---------------------------------------------------------------------------
# Compiled regex constants
# ---------------------------------------------------------------------------

_SCHOOL_NAME_HINT_RE = re.compile(
    r"\b(elementary|middle|high|academy|campus|school)\b",
    re.IGNORECASE,
)
_STAFF_ROLE_TITLE_HINT_RE = re.compile(
    r"\b(principal|assistant\s+principal|teacher|counselor|counsellor|coach|librarian|superintendent|nurse|psychologist|social\s+worker|position\s+title|job\s+title|role)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _norm_key(value: Any) -> str:
    return str(value or "").strip().lower()


# ---------------------------------------------------------------------------
# Column-name predicates
# ---------------------------------------------------------------------------


def _is_preferred_name_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    return token in {"preferred_first_name", "preferred_last_name"} or (
        token.startswith("preferred_") and token.endswith("_name")
    )


def _is_canonical_name_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    return token in {"first_name", "last_name"}


def _has_canonical_name_columns(*, rows: Sequence[Mapping[str, Any]]) -> bool:
    names = {str(row.get("column_name") or "").strip().lower() for row in rows}
    return "first_name" in names or "last_name" in names


def _is_student_identity_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    if _is_preferred_name_column_name(token):
        return False
    if token in {"first_name", "last_name", "display_name", "safe_display_name"}:
        return True
    if token.startswith("k_student"):
        return True
    if "student_id" in token:
        return True
    return False


def _is_name_column_needed_for_prompt(*, prompt: str, column_name: str) -> bool:
    text = str(prompt or "").lower()
    col = str(column_name or "").strip().lower()
    if col == "":
        return False
    wants_preferred = _prompt_explicitly_requests_preferred_name(text)
    if "first name" in text and (
        (wants_preferred and col == "preferred_first_name")
        or (not wants_preferred and col == "first_name")
    ):
        return True
    if "last name" in text and (
        (wants_preferred and col == "preferred_last_name")
        or (not wants_preferred and col == "last_name")
    ):
        return True
    if ("named " in text or "name of " in text) and (
        (wants_preferred and col in {"preferred_first_name", "preferred_last_name"})
        or (not wants_preferred and col in {"first_name", "last_name", "display_name", "safe_display_name"})
    ):
        return True
    return False


def _is_adm_signal_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    if token in {"normalized_adm", "report_period", "school_year", "grade_level_adm", "is_primary_school"}:
        return True
    if "adm" in token:
        return True
    return False


def _has_adm_signal_columns(rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        col_name = str(row.get("column_name") or "").strip().lower()
        if _is_adm_signal_column_name(col_name):
            return True
    return False


def _has_adm_metric(capabilities: Mapping[str, Any]) -> bool:
    for row in list(capabilities.get("domain_metrics") or []):
        if not isinstance(row, Mapping):
            continue
        key = str(row.get("metric_key") or "").strip().lower()
        label = str(row.get("label") or "").strip().lower()
        if "adm" in key or "average daily membership" in label or "adm" in label:
            return True
    return False


def _is_city_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    return token == "city" or token.endswith("_city") or "city_name" in token


def _is_state_school_code_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    return "state_school_code" in token


def _is_technical_school_key_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    if token in {"k_school", "school_key", "nces_school_code"}:
        return True
    if token.startswith("k_") and "school" in token:
        return True
    return False


def _is_preferred_state_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "" or _is_state_school_code_name(token):
        return False
    if token in {"state_code", "state_abbr", "state_name"}:
        return True
    if token.endswith("_state_code") or token.endswith("_state_abbr") or token.endswith("_state_name"):
        return True
    return False


def _has_preferred_state_column(*, rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        col_name = str(row.get("column_name") or "").strip().lower()
        if _is_preferred_state_column_name(col_name):
            return True
    return False


def _is_calendar_day_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    return token in {"calendar_date", "school_calendar_date"} or (
        "calendar" in token and "date" in token
    )


def _is_birth_date_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    return token in {"birth_date", "date_of_birth", "dob"} or (
        "birth" in token and "date" in token
    )


def _is_age_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    return token == "age" or token.endswith("_age") or token.startswith("age_")


def _is_school_day_flag_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    return token in {"is_school_day", "school_day_flag", "instructional_day_flag"} or (
        "school_day" in token or "instructional_day" in token
    )


def _is_non_instructional_day_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    return (
        "non_instructional" in token
        or "noninstructional" in token
        or "day_off" in token
        or "days_off" in token
    )


def _has_calendar_day_columns(rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        if _is_calendar_day_column_name(str(row.get("column_name") or "")):
            return True
    return False


def _has_birth_date_columns(rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        if _is_birth_date_column_name(str(row.get("column_name") or "")):
            return True
    return False


def _has_age_columns(rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        if _is_age_column_name(str(row.get("column_name") or "")):
            return True
    return False


def _has_school_day_flag_columns(rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        col_name = str(row.get("column_name") or "")
        if _is_school_day_flag_column_name(col_name) or _is_non_instructional_day_column_name(col_name):
            return True
    return False


def _has_school_name_column(*, rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        col_name = str(row.get("column_name") or "").strip().lower()
        if col_name == "school_name":
            return True
    return False


def _is_staff_role_title_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    if token == "":
        return False
    return token in {"position_title", "classroom_position", "job_title", "role_title", "staff_role"}


def _is_staff_classification_column_name(col_name: str) -> bool:
    token = str(col_name or "").strip().lower()
    return token == "staff_classification" or token.endswith("_classification")


def _has_staff_role_title_column(*, rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        col_name = str(row.get("column_name") or "").strip().lower()
        if _is_staff_role_title_column_name(col_name):
            return True
    return False


def _has_subgroup_column(rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        col_name = str(row.get("column_name") or "").strip().lower()
        if any(token in col_name for token in ("race", "ethnicity", "hispanic", "latino")):
            return True
    return False


def _has_student_identity_column(rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        col_name = str(row.get("column_name") or "").strip().lower()
        if _is_student_identity_column_name(col_name):
            return True
    return False


def _has_staff_identity_column(rows: Sequence[Mapping[str, Any]]) -> bool:
    for row in rows:
        col_name = str(row.get("column_name") or "").strip().lower()
        if any(
            token in col_name
            for token in (
                "staff_unique_id",
                "local_staff_id",
                "staff_classification",
                "position_title",
                "classroom_position",
                "email_address",
            )
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# Prompt preference checks (column-selection-specific)
# ---------------------------------------------------------------------------


def _prompt_explicitly_requests_staff_classification(prompt: str) -> bool:
    text = f" {str(prompt or '').strip().lower()} "
    if text.strip() == "":
        return False
    explicit_phrases = (
        " staff classification ",
        " classification code ",
        " classification ",
        " staff class ",
        " class code ",
    )
    return any(phrase in text for phrase in explicit_phrases)


def _prompt_explicitly_requests_school_key(prompt: str) -> bool:
    text = f" {str(prompt or '').strip().lower()} "
    if text.strip() == "":
        return False
    explicit_phrases = (
        " k_school ",
        " school key ",
        " school keys ",
        " school id ",
        " school ids ",
        " school code ",
        " school codes ",
        " nces ",
    )
    return any(phrase in text for phrase in explicit_phrases)


def _prompt_prefers_human_school_name_filter(prompt: str) -> bool:
    text = f" {str(prompt or '').strip().lower()} "
    if text.strip() == "":
        return False
    has_school_context = any(
        token in text
        for token in (
            " school ",
            " schools ",
            " staff ",
            " teacher ",
            " teachers ",
            " principal ",
            " assistant principal ",
            " counselor ",
            " counsellor ",
        )
    )
    if not has_school_context and _SCHOOL_NAME_HINT_RE.search(text) is not None:
        has_school_context = True
    has_lookup_phrase = any(token in text for token in (" for ", " at ", " in "))
    return has_school_context and has_lookup_phrase


def _prompt_prefers_staff_role_title_filter(prompt: str) -> bool:
    text = f" {str(prompt or '').strip().lower()} "
    if text.strip() == "":
        return False
    if _prompt_explicitly_requests_staff_classification(text):
        return False
    return _STAFF_ROLE_TITLE_HINT_RE.search(text) is not None


# ---------------------------------------------------------------------------
# Group entity extraction
# ---------------------------------------------------------------------------


def _extract_group_entities_for_shortlist(prompt_text: str) -> set[str]:
    text = f" {str(prompt_text or '').strip().lower()} "
    if " by " not in text:
        return set()
    segment = text.split(" by ", 1)[1]
    segment = re.split(r"\b(where|for|with|during|in|on|from)\b", segment, maxsplit=1)[0]
    parts = [part.strip() for part in re.split(r"\band\b|,", segment) if part.strip()]
    out: set[str] = set()
    for part in parts:
        token = re.sub(r"\s+", " ", part).strip().lower()
        if token == "":
            continue
        if "account" in token:
            out.add("account")
        if "territory" in token:
            out.add("territory")
        if "region" in token:
            out.add("region")
        if "district" in token:
            out.add("district")
        if "school" in token:
            out.add("school")
    return out


def _has_group_entity(entities: set[str], name: str) -> bool:
    return str(name or "").strip().lower() in entities


def _matches_group_entity_column(*, col_name: str, entities: set[str]) -> bool:
    col = str(col_name or "").strip().lower()
    if col == "":
        return False
    if _has_group_entity(entities, "account"):
        if col == "account_name":
            return True
        if col.startswith("account_") and col.endswith("_name"):
            return True
    if _has_group_entity(entities, "territory"):
        if col == "territory_name":
            return True
        if col.startswith("territory_") and col.endswith("_name"):
            return True
    if _has_group_entity(entities, "region"):
        if col == "region_name":
            return True
    if _has_group_entity(entities, "district"):
        if col in {"district_name", "lea_name"}:
            return True
    if _has_group_entity(entities, "school"):
        if col == "school_name":
            return True
    return False


# ---------------------------------------------------------------------------
# Column selection utilities
# ---------------------------------------------------------------------------


def _select_keys_with_table_cap(
    *,
    ordered_keys: Sequence[str],
    row_by_key: Mapping[str, Mapping[str, Any]],
    max_columns: int,
    per_table_cap: int,
) -> List[str]:
    out: List[str] = []
    per_table: Dict[int, int] = {}
    for key in ordered_keys:
        row = row_by_key.get(key)
        if row is None:
            continue
        wtid = _to_int(row.get("workspace_table_id"))
        if wtid is None:
            continue
        count = per_table.get(wtid, 0)
        if count >= per_table_cap:
            continue
        out.append(key)
        per_table[wtid] = count + 1
        if len(out) >= max_columns:
            break
    return out


def _cap_columns_per_table(
    rows: Sequence[Mapping[str, Any]],
    *,
    max_columns: int,
    per_table_cap: int,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    per_table: Dict[int, int] = {}
    seen: set[str] = set()
    for row in rows:
        key = _norm_key(row.get("column_key"))
        if key == "" or key in seen:
            continue
        wtid = _to_int(row.get("workspace_table_id"))
        if wtid is None:
            continue
        count = per_table.get(wtid, 0)
        if count >= per_table_cap:
            continue
        out.append(dict(row))
        per_table[wtid] = count + 1
        seen.add(key)
        if len(out) >= max_columns:
            break
    return out


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Core scoring functions
# ---------------------------------------------------------------------------


def _required_column_keys(*, prompt: str, rows: Sequence[Mapping[str, Any]]) -> List[str]:
    required: List[str] = []
    text = str(prompt or "").lower()
    group_entities = _extract_group_entities_for_shortlist(text)
    city_state_pattern = _prompt_has_city_state_pattern(text)
    prefer_human_school_filter = (
        _prompt_prefers_human_school_name_filter(text)
        and _has_school_name_column(rows=rows)
        and not _prompt_explicitly_requests_school_key(text)
    )
    prefer_staff_role_title_filter = (
        _prompt_prefers_staff_role_title_filter(text)
        and _has_staff_role_title_column(rows=rows)
    )
    prefer_canonical_name_columns = (
        _prompt_prefers_canonical_name_columns(text)
        and _has_canonical_name_columns(rows=rows)
    )
    prompt_has_adm_intent = _prompt_has_adm_intent(text)
    for row in rows:
        key = _norm_key(row.get("column_key"))
        col_name = str(row.get("column_name") or "").strip().lower()
        if key == "":
            continue
        if _matches_group_entity_column(col_name=col_name, entities=group_entities):
            required.append(key)
            continue
        if prompt_has_adm_intent and _is_adm_signal_column_name(col_name):
            required.append(key)
            continue
        if city_state_pattern:
            if _is_city_column_name(col_name):
                required.append(key)
                continue
            if _is_preferred_state_column_name(col_name):
                required.append(key)
                continue
            if _is_state_school_code_name(col_name):
                continue
        if prefer_human_school_filter:
            if col_name == "school_name":
                required.append(key)
                continue
            if _is_technical_school_key_name(col_name):
                continue
        if prefer_staff_role_title_filter:
            if _is_staff_role_title_column_name(col_name):
                required.append(key)
                continue
            if _is_staff_classification_column_name(col_name):
                continue
        if prefer_canonical_name_columns:
            if _is_canonical_name_column_name(col_name):
                required.append(key)
                continue
            if _is_preferred_name_column_name(col_name):
                continue
        if _prompt_has_subgroup(text) and any(
            token in col_name for token in ("race", "ethnicity", "hispanic", "latino")
        ):
            required.append(key)
            continue
        if "county" in text and ("county" in col_name or "county" in key):
            required.append(key)
            continue
        if "district" in text and any(token in col_name for token in ("district", "lea_name", "lea")):
            required.append(key)
            continue
        if _looks_like_list_students_prompt(text) and _is_student_identity_column_name(col_name):
            required.append(key)
    return _dedupe_text_items(required)[:10]


def _column_heuristic_boost(*, prompt: str, row: Mapping[str, Any]) -> float:
    col_name = str(row.get("column_name") or "").strip().lower()
    key = _norm_key(row.get("column_key"))
    score = 0.0
    text = str(prompt or "").lower()
    group_entities = _extract_group_entities_for_shortlist(text)
    city_state_pattern = _prompt_has_city_state_pattern(text)
    prefer_human_school_filter = (
        _prompt_prefers_human_school_name_filter(text)
        and not _prompt_explicitly_requests_school_key(text)
    )
    prefer_staff_role_title_filter = _prompt_prefers_staff_role_title_filter(text)
    prefer_canonical_name_columns = _prompt_prefers_canonical_name_columns(text)
    prompt_has_adm_intent = _prompt_has_adm_intent(text)
    prompt_has_age_extreme = _prompt_has_age_extreme(text)
    prompt_has_birth_month = _prompt_has_birth_month_constraint(text)
    prompt_has_calendar_days_off = _prompt_has_calendar_days_off(text)
    if _has_group_entity(group_entities, "account"):
        if col_name == "account_name":
            score += 0.42
        elif col_name in {"account_id", "account_type"}:
            score -= 0.22
    if _has_group_entity(group_entities, "territory"):
        if col_name == "territory_name":
            score += 0.4
        elif col_name == "territory_id":
            score -= 0.16
    if _has_group_entity(group_entities, "region"):
        if col_name == "region_name":
            score += 0.3
        elif col_name == "region_code":
            score -= 0.12
    if prompt_has_adm_intent:
        if _is_adm_signal_column_name(col_name):
            score += 0.42
        elif any(token in col_name for token in ("calendar", "term", "semester", "grading_period")):
            score -= 0.18
    if prompt_has_age_extreme:
        if _is_birth_date_column_name(col_name):
            score += 0.56
        if _is_age_column_name(col_name):
            score += 0.48
    if prompt_has_birth_month and _is_birth_date_column_name(col_name):
        score += 0.62
    if prompt_has_calendar_days_off:
        if _is_calendar_day_column_name(col_name):
            score += 0.48
        if _is_school_day_flag_column_name(col_name):
            score += 0.52
        if _is_non_instructional_day_column_name(col_name):
            score += 0.54
    if city_state_pattern:
        if _is_city_column_name(col_name):
            score += 0.36
        elif _is_preferred_state_column_name(col_name):
            score += 0.34
        if _is_state_school_code_name(col_name):
            score -= 0.45
        if "county" in col_name or "county" in key:
            score -= 0.22
    if prefer_human_school_filter:
        if col_name == "school_name":
            score += 0.34
        if col_name in {"lea_name", "district_name"}:
            score += 0.18
        if _is_technical_school_key_name(col_name):
            score -= 0.42
    if prefer_staff_role_title_filter:
        if _is_staff_role_title_column_name(col_name):
            score += 0.44
        if _is_staff_classification_column_name(col_name):
            score -= 0.4
    if prefer_canonical_name_columns:
        if _is_canonical_name_column_name(col_name):
            score += 0.28
        if _is_preferred_name_column_name(col_name):
            score -= 0.34
    if _prompt_has_subgroup(text) and any(
        token in col_name for token in ("race", "ethnicity", "hispanic", "latino")
    ):
        score += 0.45
    if _looks_like_list_students_prompt(text) and _is_student_identity_column_name(col_name):
        score += 0.22
    if "county" in text and ("county" in key or "county" in col_name):
        score += 0.16
    if "district" in text and any(token in col_name for token in ("district", "lea_name", "lea")):
        score += 0.16
    return score
