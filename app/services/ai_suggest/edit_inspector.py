# app/services/ai_suggest/edit_inspector.py
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.services.ai_suggest.utils import (
    COUNTRY_ABBR_TO_NAME,
    COUNTRY_NAME_TO_ABBR,
    ORDINAL_NUM_TO_INT,
    ORDINAL_NUM_TO_WORD,
    ORDINAL_WORD_TO_INT,
    ORDINAL_WORD_TO_NUM,
    US_STATE_ABBR_TO_NAME,
    US_STATE_NAME_TO_ABBR,
)


def _normalize_geo_key(value: str) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _expand_geo_literal(value: str) -> List[str]:
    original = str(value or "").strip()
    if not original:
        return []
    key = _normalize_geo_key(original)
    expanded: List[str] = [original]

    matched_state = False
    if key in US_STATE_NAME_TO_ABBR:
        expanded.append(US_STATE_NAME_TO_ABBR[key])
        matched_state = True
    elif key in US_STATE_ABBR_TO_NAME:
        expanded.append(US_STATE_ABBR_TO_NAME[key])
        matched_state = True

    if key in COUNTRY_NAME_TO_ABBR:
        expanded.append(COUNTRY_NAME_TO_ABBR[key])
    elif key in COUNTRY_ABBR_TO_NAME and not matched_state:
        expanded.append(COUNTRY_ABBR_TO_NAME[key])

    deduped: List[str] = []
    seen: set[str] = set()
    for item in expanded:
        item_text = str(item or "").strip()
        if not item_text:
            continue
        dedupe_key = item_text.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(item_text)
    return deduped


def _expand_ordinal_literal(value: str) -> List[str]:
    original = str(value or "").strip()
    if not original:
        return []
    key = _normalize_geo_key(original)
    expanded: List[str] = [original]
    if key in ORDINAL_NUM_TO_WORD:
        expanded.append(ORDINAL_NUM_TO_WORD[key])
    elif key in ORDINAL_WORD_TO_NUM:
        expanded.append(ORDINAL_WORD_TO_NUM[key])

    deduped: List[str] = []
    seen: set[str] = set()
    for item in expanded:
        item_text = str(item or "").strip()
        if not item_text:
            continue
        dedupe_key = item_text.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(item_text)
    return deduped


def _expand_filter_literal_aliases(value: str) -> List[str]:
    original = str(value or "").strip()
    if not original:
        return []
    merged: List[str] = []
    for item in _expand_geo_literal(original):
        merged.extend(_expand_ordinal_literal(item))
    deduped: List[str] = []
    seen: set[str] = set()
    for item in merged:
        item_text = str(item or "").strip()
        if not item_text:
            continue
        key = item_text.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item_text)
    return deduped


def _is_grade_column_name(column_name: str) -> bool:
    name = str(column_name or "").strip().lower()
    return "grade" in name


def _to_grade_integer(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if not isinstance(value, str):
        return None

    text = _normalize_geo_key(value)
    if not text:
        return None

    if text in ORDINAL_NUM_TO_INT:
        return ORDINAL_NUM_TO_INT[text]
    if text in ORDINAL_WORD_TO_INT:
        return ORDINAL_WORD_TO_INT[text]

    if re.fullmatch(r"\d{1,2}", text):
        return int(text)

    match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)\b", text)
    if match:
        return int(match.group(1))

    for word, number in ORDINAL_WORD_TO_INT.items():
        if re.search(rf"\b{re.escape(word)}\b", text):
            return int(number)

    match = re.search(r"\bgrade\s+(\d{1,2})\b", text)
    if match:
        return int(match.group(1))
    return None


def edits_reference_columns(edits: list[dict]) -> bool:
    for edit in edits or []:
        if not isinstance(edit, dict):
            continue
        if str(edit.get("op") or "") in {"addSelect", "addFilter", "addGroupBy", "addAggregate", "addSort"}:
            return True
    return False


def edits_have_aggregate(edits: list[dict]) -> bool:
    for edit in edits or []:
        if not isinstance(edit, dict):
            continue
        if str(edit.get("op") or "") == "addAggregate":
            return True
    return False


def edits_have_groupby(edits: list[dict]) -> bool:
    for edit in edits or []:
        if not isinstance(edit, dict):
            continue
        if str(edit.get("op") or "") == "addGroupBy":
            return True
    return False


def edits_have_sorting(edits: list[dict]) -> bool:
    for edit in edits or []:
        if not isinstance(edit, dict):
            continue
        if str(edit.get("op") or "") == "addSort":
            return True
    return False


def count_add_select_edits(edits: list[dict]) -> int:
    return sum(1 for e in edits or [] if isinstance(e, dict) and e.get("op") == "addSelect")


def has_identifier_projection(edits: list[dict]) -> bool:
    identifier_names = {"id", "student_id", "first_name", "last_name"}
    for e in edits or []:
        if not isinstance(e, dict):
            continue
        if e.get("op") != "addSelect":
            continue
        col = e.get("col")
        if not isinstance(col, dict):
            continue
        name = str(col.get("columnName") or "").lower()
        if name in identifier_names:
            return True
    return False


def is_aggregation_only(edits: list[dict]) -> bool:
    has_aggregate = False
    has_select = False
    for edit in edits or []:
        if not isinstance(edit, dict):
            continue
        op = str(edit.get("op") or "")
        if op == "addAggregate":
            has_aggregate = True
        elif op == "addSelect":
            has_select = True
    return has_aggregate and not has_select


def _column_ref_identity(col: dict) -> tuple:
    model_column_id = col.get("modelColumnId")
    if model_column_id is not None:
        try:
            return ("mid", int(model_column_id))
        except (TypeError, ValueError):
            pass
    return (
        "wt_col",
        col.get("workspaceTableId"),
        str(col.get("columnName") or "").strip().lower(),
    )


def extract_column_refs_from_edits(edits: list[dict]) -> list[dict]:
    collected: list[dict] = []
    seen: set[tuple] = set()
    for edit in edits or []:
        if not isinstance(edit, dict):
            continue
        op = str(edit.get("op") or "")
        if op not in {"addFilter", "addSelect", "addGroupBy", "addAggregate", "addSort"}:
            continue
        col = edit.get("col")
        if not isinstance(col, dict):
            continue
        identity = _column_ref_identity(col)
        if identity in seen:
            continue
        seen.add(identity)
        collected.append(dict(col))
    return collected


def determine_default_aggregate_column(edits: list[dict]) -> Optional[dict]:
    for edit in edits or []:
        if not isinstance(edit, dict):
            continue
        if str(edit.get("op") or "") == "addSelect" and isinstance(edit.get("col"), dict):
            return dict(edit["col"])
    for edit in edits or []:
        if not isinstance(edit, dict):
            continue
        if str(edit.get("op") or "") == "addFilter" and isinstance(edit.get("col"), dict):
            return dict(edit["col"])
    return None


def determine_default_groupby_columns(edits: list[dict]) -> list[dict]:
    has_aggregate = edits_have_aggregate(edits)
    has_groupby = edits_have_groupby(edits)
    if has_aggregate and not has_groupby:
        candidates = [
            edit.get("col")
            for edit in edits or []
            if isinstance(edit, dict)
            and str(edit.get("op") or "") in {"addFilter", "addSelect"}
            and isinstance(edit.get("col"), dict)
        ]
    else:
        candidates = extract_column_refs_from_edits(edits)
        if len(candidates) != 1:
            return []

    out: list[dict] = []
    seen: set[tuple] = set()
    for col in candidates:
        if not isinstance(col, dict):
            continue
        if not str(col.get("columnName") or "").strip():
            continue
        identity = _column_ref_identity(col)
        if identity in seen:
            continue
        seen.add(identity)
        out.append(dict(col))
    return out


def determine_default_sort(edits: list[dict], prompt: str) -> Optional[dict]:
    prompt_lc = (prompt or "").lower()
    if edits_have_aggregate(edits):
        default_agg_col = None
        for edit in edits or []:
            if not isinstance(edit, dict):
                continue
            if str(edit.get("op") or "") != "addAggregate":
                continue
            if isinstance(edit.get("col"), dict):
                default_agg_col = dict(edit["col"])
                break
        if default_agg_col is None:
            default_agg_col = determine_default_aggregate_column(edits)
        if isinstance(default_agg_col, dict):
            return {"op": "addSort", "col": dict(default_agg_col), "dir": "desc"}

    source_cols = [
        edit.get("col")
        for edit in edits or []
        if isinstance(edit, dict)
        and str(edit.get("op") or "") in {"addSelect", "addFilter"}
        and isinstance(edit.get("col"), dict)
    ]
    if not source_cols:
        return None
    chosen = dict(source_cols[0])

    descending_tokens = ("top", "highest", "most", "descending")
    ascending_tokens = ("lowest", "least", "ascending")
    if any(token in prompt_lc for token in descending_tokens):
        return {"op": "addSort", "col": chosen, "dir": "desc"}
    if any(token in prompt_lc for token in ascending_tokens):
        return {"op": "addSort", "col": chosen, "dir": "asc"}
    if "sorted by" in prompt_lc or "order by" in prompt_lc or "rank" in prompt_lc:
        return {"op": "addSort", "col": chosen, "dir": "asc"}
    return None


def get_identifier_candidates(candidates: list[dict]) -> list[dict]:
    identifier_order = ("student_id", "first_name", "last_name", "id")
    by_name: dict[str, list[dict]] = {key: [] for key in identifier_order}
    for candidate in candidates or []:
        if not isinstance(candidate, dict):
            continue
        column_name = str(candidate.get("columnName") or "").strip().lower()
        if column_name not in by_name:
            continue
        by_name[column_name].append(candidate)

    selected: list[dict] = []
    for name in identifier_order:
        pool = by_name[name]
        if not pool:
            continue
        selected.append(pool[0])
        if len(selected) >= 2:
            break
    return selected
