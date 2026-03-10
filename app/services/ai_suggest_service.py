from __future__ import annotations

import json
import logging
import re
import time
from copy import deepcopy
from typing import Any, Dict, List, Optional
from uuid import uuid4

import requests
from pydantic import ValidationError

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import VLLM_BASE_URL, VLLM_MODEL, VLLM_TIMEOUT
from app.models.ai_suggest import (
    AddAggregateEdit,
    AddGroupByEdit,
    AddSelectEdit,
    AddSortEdit,
    SetDomainEdit,
    SqlColumnKey,
    SuggestAPIResponse,
    SuggestModelResponse,
    SuggestRequest,
)
from app.ports.sql_executor import ForgeQueryPort
from app.services.llm.io_logging import (
    log_llm_exception,
    log_llm_request,
    log_llm_response,
    new_llm_request_id,
)
from app.services.sqljson_apply_service import apply_edits

logger = logging.getLogger(__name__)

DEFAULT_TEMPERATURE = 0.2
DEFAULT_TOP_P = 0.8
DEFAULT_MAX_TOKENS = 700
MAX_REPAIR_PREVIOUS_OUTPUT_CHARS = 3000
MAX_RAW_MODEL_LOG_CHARS = 10000
ALLOWED_EDIT_OPS = {"setDomain", "addSelect", "addFilter", "addGroupBy", "addAggregate", "addSort"}
_ALLOWED_COL_KEYS = {"modelColumnId", "columnName", "workspaceTableId", "exprId", "alias"}
LEGACY_FILTER_OPERATOR_MAP = {
    "=": "equals",
    "==": "equals",
    "!=": "not_equals",
    "<>": "not_equals",
    "ne": "not_equals",
    "not_equal": "not_equals",
    "not_equals": "not_equals",
    "in": "in",
    "not in": "not_in",
    "not_in": "not_in",
    "gte": "gte",
    ">=": "gte",
    "lte": "lte",
    "<=": "lte",
    "is null": "is_null",
    "is_null": "is_null",
    "is not null": "is_not_null",
    "is_not_null": "is_not_null",
    "between": "between",
}
US_STATE_NAME_TO_ABBR = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}
US_STATE_ABBR_TO_NAME = {abbr.lower(): name.title() for name, abbr in US_STATE_NAME_TO_ABBR.items()}
COUNTRY_NAME_TO_ABBR = {
    "united states": "US",
    "usa": "US",
    "u.s.": "US",
    "u.s.a.": "US",
    "mexico": "MX",
    "canada": "CA",
}
COUNTRY_ABBR_TO_NAME = {
    "us": "United States",
    "mx": "Mexico",
    "ca": "Canada",
}
ORDINAL_NUM_TO_WORD = {
    "1st": "first",
    "2nd": "second",
    "3rd": "third",
    "4th": "fourth",
    "5th": "fifth",
    "6th": "sixth",
    "7th": "seventh",
    "8th": "eighth",
    "9th": "ninth",
    "10th": "tenth",
    "11th": "eleventh",
    "12th": "twelfth",
    "13th": "thirteenth",
    "14th": "fourteenth",
    "15th": "fifteenth",
    "16th": "sixteenth",
    "17th": "seventeenth",
    "18th": "eighteenth",
    "19th": "nineteenth",
    "20th": "twentieth",
}
ORDINAL_WORD_TO_NUM = {word: num for num, word in ORDINAL_NUM_TO_WORD.items()}
ORDINAL_NUM_TO_INT = {
    token: int(re.match(r"^(\d+)", token).group(1))  # type: ignore[union-attr]
    for token in ORDINAL_NUM_TO_WORD
}
ORDINAL_WORD_TO_INT = {word: ORDINAL_NUM_TO_INT[token] for word, token in ORDINAL_WORD_TO_NUM.items()}
_QUOTED_LITERAL_RE = re.compile(r"'[^']+'|\"[^\"]+\"")
_YEAR_LITERAL_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_NUMBER_LITERAL_RE = re.compile(r"\b\d+\b")
_BOOLEAN_LITERAL_RE = re.compile(r"\b(?:true|false)\b", re.IGNORECASE)
_LABEL_VALUE_LITERAL_RE = re.compile(
    r"\b(?:name|first\s+name|last\s+name|student|teacher|school|district|city|state|email)\b\s+[A-Z][a-zA-Z'\-]*\b"
)


def _sanitize_col(col: dict) -> dict:
    return {k: col.get(k) for k in _ALLOWED_COL_KEYS if k in col}


def prompt_contains_literal(prompt: str) -> bool:
    if not isinstance(prompt, str):
        return False
    text = prompt.strip()
    if not text:
        return False
    if ":" in text:
        return True
    if _QUOTED_LITERAL_RE.search(text):
        return True
    if _YEAR_LITERAL_RE.search(text):
        return True
    if _NUMBER_LITERAL_RE.search(text):
        return True
    if _BOOLEAN_LITERAL_RE.search(text):
        return True
    if _LABEL_VALUE_LITERAL_RE.search(text):
        return True
    return False


def prompt_implies_aggregation(prompt: str) -> bool:
    if not isinstance(prompt, str):
        return False
    text = prompt.lower()
    for token in ("how many", "count", "total", "number of", "sum", "average", "avg"):
        if token in text:
            return True
    return False


def prompt_requests_distinct_count(prompt: str) -> bool:
    if not isinstance(prompt, str):
        return False
    text = prompt.lower()
    tokens = ("distinct", "unique", "deduplicated", "deduped", "non-duplicate", "without duplicates")
    return any(token in text for token in tokens)


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


def prompt_implies_grouping(prompt: str) -> bool:
    if not isinstance(prompt, str):
        return False
    text = f" {prompt.lower()} "
    tokens = (
        " by ",
        " per ",
        " grouped by ",
        " for each ",
        " count by ",
        " sum by ",
        " average by ",
        " breakdown by ",
        " distribution by ",
    )
    return any(token in text for token in tokens)


def prompt_implies_sorting(prompt: str) -> bool:
    if not isinstance(prompt, str):
        return False
    text = prompt.lower()
    tokens = (
        "sorted by",
        "order by",
        "top",
        "highest",
        "lowest",
        "most",
        "least",
        "rank",
        "descending",
        "ascending",
    )
    return any(token in text for token in tokens)


def prompt_implies_entity_listing(prompt: str) -> bool:
    if not isinstance(prompt, str):
        return False
    text = prompt.lower()
    intent_tokens = ("show", "list", "display", "all", "give me")
    entity_tokens = ("student", "students", "school", "schools", "course", "courses")
    return any(token in text for token in intent_tokens) and any(token in text for token in entity_tokens)


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


def _workspace_table_ids_from_edits(edits: list[dict]) -> list[int]:
    table_ids: set[int] = set()
    for edit in edits or []:
        if not isinstance(edit, dict):
            continue
        op = str(edit.get("op") or "")
        if op not in {"addSelect", "addFilter", "addGroupBy", "addAggregate", "addSort"}:
            continue
        col = edit.get("col")
        if not isinstance(col, dict):
            continue
        wtid = col.get("workspaceTableId")
        try:
            if wtid is not None:
                table_ids.add(int(wtid))
        except (TypeError, ValueError):
            continue
    return sorted(table_ids)


def _placeholders(prefix: str, count: int) -> str:
    return ", ".join(f":{prefix}{i}" for i in range(count))


def infer_domain_from_columns(
    workspace_id: str,
    edits: list[dict],
    sql_executor: ForgeQueryPort,
) -> Optional[int]:
    table_ids = _workspace_table_ids_from_edits(edits)
    if not table_ids:
        return None

    placeholders = _placeholders("wtid", len(table_ids))
    sql = f"""
    SELECT DISTINCT dwt.domain_id
    FROM domain_workspace_table dwt
    WHERE dwt.workspace_id = :workspace_id
      AND dwt.workspace_table_id IN ({placeholders})
    """
    params: Dict[str, Any] = {"workspace_id": workspace_id}
    params.update({f"wtid{i}": int(v) for i, v in enumerate(table_ids)})

    rows = sql_executor.execute_query_mappings(sql, params)
    domain_ids: set[int] = set()
    for row in rows or []:
        try:
            domain_id = row.get("domain_id")
            if domain_id is not None:
                domain_ids.add(int(domain_id))
        except (TypeError, ValueError, AttributeError):
            continue

    if len(domain_ids) == 1:
        return next(iter(domain_ids))
    return None


class InvalidModelResponseError(RuntimeError):
    """Raised when model output cannot be parsed/validated after retry."""

    def __init__(self, details: Dict[str, Any]):
        super().__init__("Invalid model response")
        self.details = details


class AISuggestService:
    """Generates structured planner edits via a local vLLM chat endpoint."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
        temperature: float = DEFAULT_TEMPERATURE,
        top_p: float = DEFAULT_TOP_P,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        sql_executor: Optional[ForgeQueryPort] = None,
    ) -> None:
        self.base_url = (base_url or VLLM_BASE_URL).rstrip("/")
        self.model = model or VLLM_MODEL
        timeout_value = timeout if timeout is not None else VLLM_TIMEOUT
        self.timeout = int(timeout_value)
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max(600, min(800, int(max_tokens)))
        self._sql = sql_executor or ForgeMetaSQL()

    def suggest(
        self,
        suggest_request: SuggestRequest,
        *,
        valid_domain_ids: Optional[set[int]] = None,
        valid_column_keys: Optional[set[str]] = None,
    ) -> SuggestAPIResponse:
        start = time.perf_counter()
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": self._build_user_prompt(suggest_request)},
        ]
        candidate_columns = suggest_request.candidates.columns if suggest_request.candidates else []
        candidate_column_dicts = [candidate.model_dump(mode="json") for candidate in candidate_columns]
        literal_detected = prompt_contains_literal(suggest_request.prompt)
        logger.info(
            "AI suggest prompt=%s literal_detected=%s",
            suggest_request.prompt,
            literal_detected,
        )
        previous_content = ""
        last_error: Dict[str, Any] = {}
        retry_reason: Optional[str] = None
        fallback_response: Optional[SuggestAPIResponse] = None

        for attempt in (1, 2):
            attempt_messages = list(messages)
            if attempt == 2:
                if retry_reason == "missing_filters":
                    attempt_messages.append(
                        {"role": "system", "content": self._build_filter_retry_prompt()}
                    )
                elif retry_reason == "missing_domain":
                    attempt_messages.append(
                        {"role": "system", "content": self._build_domain_retry_prompt()}
                    )
                elif retry_reason == "missing_aggregate":
                    attempt_messages.append(
                        {"role": "system", "content": self._build_aggregate_retry_prompt()}
                    )
                elif retry_reason == "missing_groupby":
                    attempt_messages.append(
                        {"role": "system", "content": self._build_groupby_retry_prompt()}
                    )
                elif retry_reason == "missing_projection_completeness":
                    attempt_messages.append(
                        {"role": "system", "content": self._build_projection_completeness_retry_prompt()}
                    )
                else:
                    attempt_messages.append(
                        {
                            "role": "system",
                            "content": self._build_repair_prompt(previous_content),
                        }
                    )

            raw = self._call_chat_completion(attempt_messages)
            try:
                content = self._extract_content(raw)
            except InvalidModelResponseError as exc:
                last_error = {"attempt": attempt, **exc.details}
                logger.warning("AI suggest response content extraction failed on attempt %s: %s", attempt, exc.details)
                retry_reason = "repair"
                if attempt == 2 and fallback_response is not None:
                    logger.error(
                        "AI suggest retry failed to return parsable content; returning first valid response without filters"
                    )
                    return fallback_response
                continue
            previous_content = content
            self._log_raw_model_output(attempt, content)

            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as exc:
                last_error = {
                    "attempt": attempt,
                    "type": "json_parse_error",
                    "message": str(exc),
                    "content": content,
                }
                logger.warning("AI suggest JSON parse failed on attempt %s: %s", attempt, exc)
                retry_reason = "repair"
                if attempt == 2 and fallback_response is not None:
                    logger.error(
                        "AI suggest retry returned invalid JSON; returning first valid response without filters"
                    )
                    return fallback_response
                continue

            normalized, normalization_meta = self._normalize_model_payload(parsed)

            try:
                validated = SuggestModelResponse.model_validate(normalized)
                grounded, removed_count = self._enforce_grounding(
                    validated=validated,
                    valid_domain_ids=valid_domain_ids,
                    valid_column_keys=valid_column_keys,
                )
                edits_dicts = [edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits]
                llm_emitted_set_domain = any(
                    str(edit.get("op") or "") == "setDomain" for edit in edits_dicts
                )
                llm_emitted_add_select = any(
                    str(edit.get("op") or "") == "addSelect" for edit in edits_dicts
                )
                logger.info(
                    "AI suggest domain signal attempt=%s llm_emitted_set_domain=%s llm_emitted_add_select=%s",
                    attempt,
                    llm_emitted_set_domain,
                    llm_emitted_add_select,
                )

                inferred_domain_id: Optional[int] = None
                needs_domain = edits_reference_columns(edits_dicts)
                if not llm_emitted_set_domain and needs_domain:
                    inferred_domain_id = self._current_sqljson_domain_id(suggest_request.currentSqlJson)
                    if inferred_domain_id is not None:
                        logger.info("Domain taken from currentSqlJson: %s", inferred_domain_id)
                    else:
                        inferred_domain_id = self._fallback_domain_id(suggest_request)
                        if inferred_domain_id is not None:
                            logger.info(
                                "Domain inferred from request context fallback: %s",
                                inferred_domain_id,
                            )
                        else:
                            inferred_domain_id = self._infer_domain_safely(
                                workspace_id=suggest_request.workspaceId,
                                edits=edits_dicts,
                            )
                    if inferred_domain_id is not None:
                        grounded = SuggestModelResponse(
                            edits=[SetDomainEdit(op="setDomain", domainId=int(inferred_domain_id)), *grounded.edits],
                            explanation=grounded.explanation,
                            confidence=grounded.confidence,
                        )
                        edits_dicts = [edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits]
                        logger.info("Domain inferred deterministically: %s", inferred_domain_id)
                    elif attempt == 1:
                        logger.warning(
                            "Missing required setDomain edit with column edits. Retrying with stricter instruction."
                        )
                        retry_reason = "missing_domain"
                        continue
                    else:
                        logger.warning("Unable to determine domain.")

                projection_injected = 0
                if not is_aggregation_only(edits_dicts):
                    referenced_cols = extract_column_refs_from_edits(edits_dicts)
                    has_add_select = any(
                        str(edit.get("op") or "") == "addSelect" for edit in edits_dicts
                    )
                    if referenced_cols and not has_add_select:
                        injected_selects: list[AddSelectEdit] = []
                        existing_select_keys = {
                            _column_ref_identity(edit.get("col") or {})
                            for edit in edits_dicts
                            if isinstance(edit, dict) and str(edit.get("op") or "") == "addSelect" and isinstance(edit.get("col"), dict)
                        }
                        for col in referenced_cols:
                            if not isinstance(col, dict):
                                continue
                            if str(col.get("columnName") or "").strip() == "":
                                continue
                            identity = _column_ref_identity(col)
                            if identity in existing_select_keys:
                                continue
                            try:
                                select_edit = AddSelectEdit(
                                    op="addSelect",
                                    col=SqlColumnKey.model_validate(col),
                                    alias=str(col.get("columnName") or "").strip() or None,
                                )
                            except Exception:
                                continue
                            injected_selects.append(select_edit)
                            existing_select_keys.add(identity)
                        if injected_selects:
                            logger.info(
                                "Projection fallback triggered — injecting addSelect edits."
                            )
                            projection_injected = len(injected_selects)
                            grounded = SuggestModelResponse(
                                edits=[*injected_selects, *grounded.edits],
                                explanation=grounded.explanation,
                                confidence=grounded.confidence,
                            )
                            edits_dicts = [
                                edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits
                            ]
                logger.info(
                    "AI suggest projection fallback injected_count=%s",
                    projection_injected,
                )

                aggregation_intent = prompt_implies_aggregation(suggest_request.prompt)
                has_aggregate = edits_have_aggregate(edits_dicts)
                aggregation_fallback_injected = False
                logger.info(
                    "AI suggest aggregation signal attempt=%s aggregation_intent=%s llm_emitted_aggregate=%s",
                    attempt,
                    aggregation_intent,
                    has_aggregate,
                )
                if aggregation_intent and not has_aggregate:
                    if attempt == 1:
                        logger.warning(
                            "Missing required addAggregate edit. Retrying with stricter instruction."
                        )
                        retry_reason = "missing_aggregate"
                        continue
                    default_agg_col = determine_default_aggregate_column(edits_dicts)
                    if default_agg_col is not None:
                        try:
                            agg_edit = AddAggregateEdit(
                                op="addAggregate",
                                func="count",
                                col=SqlColumnKey.model_validate(default_agg_col),
                                alias="count_result",
                            )
                            grounded = SuggestModelResponse(
                                edits=[*grounded.edits, agg_edit],
                                explanation=grounded.explanation,
                                confidence=grounded.confidence,
                            )
                            edits_dicts = [
                                edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits
                            ]
                            aggregation_fallback_injected = True
                            logger.info(
                                "Aggregation fallback triggered — injecting addAggregate."
                            )
                        except Exception as exc:
                            logger.warning(
                                "Aggregation fallback failed to inject addAggregate: %s",
                                exc,
                            )
                    else:
                        logger.warning(
                            "Aggregation implied but no column available for fallback."
                        )

                distinct_requested = prompt_requests_distinct_count(suggest_request.prompt)
                grounded, distinct_normalized_count = self._normalize_distinct_aggregate_policy(
                    grounded,
                    distinct_requested=distinct_requested,
                )
                if distinct_normalized_count > 0:
                    edits_dicts = [
                        edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits
                    ]
                    logger.info(
                        "AI suggest aggregate distinct policy normalized_count=%s distinct_requested=%s",
                        distinct_normalized_count,
                        distinct_requested,
                    )

                grounded, geo_filter_expansion_count = self._normalize_geography_filter_aliases(grounded)
                if geo_filter_expansion_count > 0:
                    edits_dicts = [
                        edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits
                    ]
                    logger.info(
                        "AI suggest geography filter expansion count=%s",
                        geo_filter_expansion_count,
                    )

                grouping_intent = prompt_implies_grouping(suggest_request.prompt)
                has_group_by = edits_have_groupby(edits_dicts)
                grouping_injected_count = 0
                logger.info(
                    "AI suggest grouping signal attempt=%s grouping_intent=%s llm_emitted_groupby=%s",
                    attempt,
                    grouping_intent,
                    has_group_by,
                )
                if grouping_intent and not has_group_by:
                    if attempt == 1:
                        logger.warning(
                            "Missing required addGroupBy edit. Retrying with stricter instruction."
                        )
                        retry_reason = "missing_groupby"
                        continue
                    default_group_cols = determine_default_groupby_columns(edits_dicts)
                    if default_group_cols:
                        existing_group_keys = {
                            _column_ref_identity(edit.get("col") or {})
                            for edit in edits_dicts
                            if isinstance(edit, dict)
                            and str(edit.get("op") or "") == "addGroupBy"
                            and isinstance(edit.get("col"), dict)
                        }
                        injected_groupby: list[AddGroupByEdit] = []
                        for col in default_group_cols:
                            if not isinstance(col, dict):
                                continue
                            identity = _column_ref_identity(col)
                            if identity in existing_group_keys:
                                continue
                            try:
                                group_edit = AddGroupByEdit(
                                    op="addGroupBy",
                                    col=SqlColumnKey.model_validate(col),
                                )
                            except Exception:
                                continue
                            injected_groupby.append(group_edit)
                            existing_group_keys.add(identity)
                        if injected_groupby:
                            grounded = SuggestModelResponse(
                                edits=[*injected_groupby, *grounded.edits],
                                explanation=grounded.explanation,
                                confidence=grounded.confidence,
                            )
                            edits_dicts = [
                                edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits
                            ]
                            grouping_injected_count = len(injected_groupby)
                            logger.info(
                                "Grouping fallback triggered — injecting addGroupBy edits."
                            )
                    else:
                        logger.warning("Grouping implied but no column available for fallback.")

                sorting_intent = prompt_implies_sorting(suggest_request.prompt)
                has_sorting = edits_have_sorting(edits_dicts)
                sorting_injected = False
                logger.info(
                    "AI suggest sorting signal attempt=%s sorting_intent=%s llm_emitted_sorting=%s",
                    attempt,
                    sorting_intent,
                    has_sorting,
                )
                if sorting_intent and not has_sorting:
                    default_sort = determine_default_sort(edits_dicts, suggest_request.prompt)
                    if default_sort is not None:
                        try:
                            sort_edit = AddSortEdit(
                                op="addSort",
                                col=SqlColumnKey.model_validate(default_sort["col"]),
                                dir=str(default_sort.get("dir") or "asc").lower(),
                            )
                            grounded = SuggestModelResponse(
                                edits=[sort_edit, *grounded.edits],
                                explanation=grounded.explanation,
                                confidence=grounded.confidence,
                            )
                            edits_dicts = [
                                edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits
                            ]
                            sorting_injected = True
                            logger.info("Sorting fallback triggered — injecting addSort edit.")
                        except Exception as exc:
                            logger.warning("Sorting fallback failed: %s", exc)
                    else:
                        logger.warning("Sorting implied but no column available for fallback.")

                if edits_have_aggregate(edits_dicts) and not edits_have_groupby(edits_dicts):
                    pruned_edits = [
                        edit
                        for edit in grounded.edits
                        if getattr(edit, "op", "") != "addSelect"
                    ]
                    if len(pruned_edits) != len(grounded.edits):
                        grounded = SuggestModelResponse(
                            edits=pruned_edits,
                            explanation=grounded.explanation,
                            confidence=grounded.confidence,
                        )
                        edits_dicts = [
                            edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits
                        ]
                        logger.info(
                            "AI suggest aggregation cleanup removed addSelect edits for aggregation-only result"
                        )

                listing_intent = prompt_implies_entity_listing(suggest_request.prompt)
                initial_select_count = count_add_select_edits(edits_dicts)
                identifier_projection_present = has_identifier_projection(edits_dicts)
                projection_completeness_fallback_injected = 0
                logger.info(
                    (
                        "AI suggest projection completeness signal attempt=%s listing_intent=%s "
                        "initial_select_count=%s has_identifier_projection=%s"
                    ),
                    attempt,
                    listing_intent,
                    initial_select_count,
                    identifier_projection_present,
                )
                if listing_intent and initial_select_count < 2:
                    if attempt == 1:
                        logger.warning(
                            "Projection completeness retry triggered: listing intent with fewer than two addSelect edits."
                        )
                        retry_reason = "missing_projection_completeness"
                        continue

                    identifier_candidates = get_identifier_candidates(candidate_column_dicts)
                    selected_identities = {
                        _column_ref_identity(edit.get("col") or {})
                        for edit in edits_dicts
                        if isinstance(edit, dict)
                        and str(edit.get("op") or "") == "addSelect"
                        and isinstance(edit.get("col"), dict)
                    }
                    injected_selects: list[AddSelectEdit] = []
                    for candidate in identifier_candidates:
                        if count_add_select_edits(edits_dicts) + len(injected_selects) >= 2:
                            break
                        if not isinstance(candidate, dict):
                            continue
                        col_dict = {
                            "modelColumnId": candidate.get("modelColumnId"),
                            "columnName": candidate.get("columnName"),
                            "workspaceTableId": candidate.get("workspaceTableId"),
                            "exprId": None,
                            "alias": None,
                        }
                        if not str(col_dict.get("columnName") or "").strip():
                            continue
                        identity = _column_ref_identity(col_dict)
                        if identity in selected_identities:
                            continue
                        try:
                            select_edit = AddSelectEdit(
                                op="addSelect",
                                col=SqlColumnKey.model_validate(col_dict),
                                alias=str(col_dict.get("columnName") or "").strip() or None,
                            )
                        except Exception:
                            continue
                        injected_selects.append(select_edit)
                        selected_identities.add(identity)
                    if injected_selects:
                        grounded = SuggestModelResponse(
                            edits=[*injected_selects, *grounded.edits],
                            explanation=grounded.explanation,
                            confidence=grounded.confidence,
                        )
                        edits_dicts = [
                            edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits
                        ]
                        projection_completeness_fallback_injected = len(injected_selects)
                        logger.info("Projection completeness fallback triggered.")
                    logger.info(
                        "AI suggest projection completeness fallback injected_count=%s final_select_count=%s",
                        projection_completeness_fallback_injected,
                        count_add_select_edits(edits_dicts),
                    )

                reordered_edits = self._order_setdomain_first(grounded.edits)
                if reordered_edits != list(grounded.edits):
                    grounded = SuggestModelResponse(
                        edits=reordered_edits,
                        explanation=grounded.explanation,
                        confidence=grounded.confidence,
                    )
                    edits_dicts = [
                        edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits
                    ]

                sqljson_seed = self._seed_sqljson_domain_if_missing(
                    current_sqljson=suggest_request.currentSqlJson,
                    suggest_request=suggest_request,
                    validated=grounded,
                )
                sqljson = apply_edits(
                    sqljson_seed,
                    grounded.edits,
                    prompt=suggest_request.prompt,
                )
                self._enforce_sqljson_aggs_from_edits(sqljson, edits_dicts)
                self._enforce_sqljson_sorting_from_edits(sqljson, edits_dicts)
                if sqljson.get("domainId") is None and edits_reference_columns(edits_dicts):
                    post_inferred_domain = inferred_domain_id
                    if post_inferred_domain is None:
                        post_inferred_domain = self._infer_domain_safely(
                            workspace_id=suggest_request.workspaceId,
                            edits=edits_dicts,
                        )
                    if post_inferred_domain is None:
                        post_inferred_domain = self._fallback_domain_id(suggest_request)
                    if post_inferred_domain is not None:
                        sqljson["domainId"] = int(post_inferred_domain)
                        logger.info("Final domainId enforced=%s", sqljson["domainId"])
                    else:
                        logger.warning("Unable to determine domain.")
                        grounded = SuggestModelResponse(
                            edits=[],
                            explanation=(
                                f"{grounded.explanation} Unable to determine domain for column edits."
                            ).strip(),
                            confidence=max(0.0, float(grounded.confidence) - 0.4),
                        )
                        edits_dicts = []
                        sqljson = apply_edits(
                            sqljson_seed,
                            grounded.edits,
                            prompt=suggest_request.prompt,
                        )

                if (
                    not isinstance(sqljson.get("aggs"), dict)
                    and not (sqljson.get("columns") or [])
                    and isinstance(sqljson.get("filters"), dict)
                ):
                    fallback_columns = self._columns_from_filter_tree(sqljson.get("filters"))
                    if fallback_columns:
                        sqljson["columns"] = fallback_columns
                        logger.info(
                            "AI suggest sqlJson projection safety net populated columns=%s",
                            len(fallback_columns),
                        )

                filter_count = sum(
                    1 for edit in grounded.edits if getattr(edit, "op", "") == "addFilter"
                )
                final_edits = len(grounded.edits)
                final_select_count = count_add_select_edits(edits_dicts)
                final_columns_count = len(sqljson.get("columns") or [])
                logger.info(
                    (
                        "AI suggest edit stats attempt=%s final_edits=%s filter_edits=%s "
                        "literal_detected=%s final_domain_id=%s final_columns_count=%s "
                        "aggregation_intent=%s distinct_requested=%s has_aggregate=%s aggregation_fallback_injected=%s "
                        "geo_filter_expansion_count=%s "
                        "listing_intent=%s initial_select_count=%s final_select_count=%s projection_completeness_fallback_injected=%s "
                        "grouping_intent=%s has_groupby=%s grouping_fallback_injected=%s "
                        "sorting_intent=%s has_sorting=%s sorting_fallback_injected=%s "
                        "final_aggs_enabled=%s final_sorting_count=%s"
                    ),
                    attempt,
                    final_edits,
                    filter_count,
                    literal_detected,
                    sqljson.get("domainId"),
                    final_columns_count,
                    aggregation_intent,
                    distinct_requested,
                    edits_have_aggregate(edits_dicts),
                    aggregation_fallback_injected,
                    geo_filter_expansion_count,
                    listing_intent,
                    initial_select_count,
                    final_select_count,
                    projection_completeness_fallback_injected,
                    grouping_intent,
                    edits_have_groupby(edits_dicts),
                    grouping_injected_count,
                    sorting_intent,
                    edits_have_sorting(edits_dicts),
                    sorting_injected,
                    isinstance(sqljson.get("aggs"), dict),
                    len(sqljson.get("sorting") or []),
                )
                if literal_detected and filter_count == 0 and attempt == 1:
                    logger.warning(
                        "Missing required addFilter edits. Retrying with stricter instruction."
                    )
                    retry_reason = "missing_filters"
                    fallback_response = SuggestAPIResponse(
                        edits=grounded.edits,
                        explanation=grounded.explanation,
                        confidence=grounded.confidence,
                        sqlJson=sqljson,
                        debug={"model": self.model, "attempts": 2},
                    )
                    continue
                if literal_detected and filter_count == 0 and attempt == 2:
                    logger.error(
                        "AI suggest retry still missing addFilter edits for literal prompt"
                    )

                latency_ms = int((time.perf_counter() - start) * 1000)
                logger.info(
                    (
                        "AI suggest completed model=%s attempts=%s llm_latency_ms=%s "
                        "invalid_edits_removed=%s normalized_key_rewrites=%s normalized_edits_dropped=%s "
                        "final_edits=%s filter_edits=%s"
                    ),
                    self.model,
                    attempt,
                    latency_ms,
                    removed_count,
                    normalization_meta.get("rewritten_ops", 0),
                    normalization_meta.get("dropped_edits", 0),
                    final_edits,
                    filter_count,
                )
                return SuggestAPIResponse(
                    edits=grounded.edits,
                    explanation=grounded.explanation,
                    confidence=grounded.confidence,
                    sqlJson=sqljson,
                    debug={"model": self.model, "attempts": attempt},
                )
            except ValidationError as exc:
                last_error = {
                    "attempt": attempt,
                    "type": "schema_validation_error",
                    "message": "Model output did not match required schema",
                    "errors": exc.errors(include_url=False),
                    "content": content,
                }
                logger.warning("AI suggest schema validation failed on attempt %s: %s", attempt, exc)
                retry_reason = "repair"
                if attempt == 2 and fallback_response is not None:
                    logger.error(
                        "AI suggest retry returned invalid schema; returning first valid response without filters"
                    )
                    return fallback_response

        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.error(
            "AI suggest failed model=%s attempts=2 llm_latency_ms=%s details=%s",
            self.model,
            latency_ms,
            last_error,
        )
        raise InvalidModelResponseError(last_error or {"type": "unknown_error"})

    def health(self) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/models"
        request_id = new_llm_request_id()
        log_llm_request(
            logger,
            client_name="AISuggestService.health",
            request_id=request_id,
            method="GET",
            url=url,
            payload=None,
        )
        try:
            response = requests.get(url, timeout=self.timeout)
        except Exception as exc:
            log_llm_exception(
                logger,
                client_name="AISuggestService.health",
                request_id=request_id,
                method="GET",
                url=url,
                message=str(exc),
            )
            raise
        log_llm_response(
            logger,
            client_name="AISuggestService.health",
            request_id=request_id,
            status_code=response.status_code,
            response_text=response.text,
        )
        response.raise_for_status()
        return response.json()

    def _call_chat_completion(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
        }
        request_id = new_llm_request_id()
        log_llm_request(
            logger,
            client_name="AISuggestService.chat",
            request_id=request_id,
            method="POST",
            url=url,
            payload=payload,
        )
        try:
            response = requests.post(url, json=payload, timeout=self.timeout)
        except Exception as exc:
            log_llm_exception(
                logger,
                client_name="AISuggestService.chat",
                request_id=request_id,
                method="POST",
                url=url,
                message=str(exc),
            )
            raise
        log_llm_response(
            logger,
            client_name="AISuggestService.chat",
            request_id=request_id,
            status_code=response.status_code,
            response_text=response.text,
        )
        response.raise_for_status()
        return response.json()

    def _extract_content(self, response_json: Dict[str, Any]) -> str:
        try:
            content = response_json["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            logger.warning("AI suggest response missing expected content path: %s", response_json)
            raise InvalidModelResponseError(
                {
                    "type": "invalid_response_shape",
                    "message": str(exc),
                }
            ) from exc

        if not isinstance(content, str):
            raise InvalidModelResponseError(
                {
                    "type": "invalid_content_type",
                    "message": f"Expected string content, got {type(content).__name__}",
                }
            )
        return content

    def _build_system_prompt(self) -> str:
        return (
            "You are QueryForge's structured planner. Return ONLY valid JSON with no markdown and no commentary. "
            "Use exactly the required schema keys and do not add extra keys. "
            "Response MUST include top-level keys: edits, explanation, confidence. "
            "Every edit object MUST use key 'op' (NOT 'operation'). "
            "For addSelect/addFilter/addGroupBy/addAggregate/addSort, use key 'col' (NOT 'columnKey'). "
            "Use SqlColumnKey objects (NOT string column keys) for edit fields. "
            "In the 'col' object, include ONLY these keys: modelColumnId, columnName, workspaceTableId, exprId, alias. "
            "Do NOT include modelTableId, modelTableName, fullName, tableAlias, dataType, nullable, or any other fields. "
            "Filter operator values MUST be one of: equals, contains, starts_with, in, gt, lt, between. "
            "Example setDomain: {\"op\":\"setDomain\",\"domainId\":1}. "
            "Example addSelect: {\"op\":\"addSelect\",\"col\":{\"modelColumnId\":351,\"columnName\":\"school_year\",\"workspaceTableId\":24},\"alias\":\"school_year\"}. "
            "Example strict col: {\"op\":\"addSelect\",\"col\":{\"modelColumnId\":1,\"columnName\":\"race\",\"workspaceTableId\":2},\"alias\":\"race\"}. "
            "Example addFilter: {\"op\":\"addFilter\",\"col\":{\"modelColumnId\":500,\"columnName\":\"race_ethnicity\",\"workspaceTableId\":24},\"operator\":\"equals\",\"value\":\"Black\"}. "
            "Example addGroupBy: {\"op\":\"addGroupBy\",\"col\":{\"modelColumnId\":351,\"columnName\":\"school_year\",\"workspaceTableId\":24}}. "
            "Example addAggregate: {\"op\":\"addAggregate\",\"func\":\"count\",\"col\":{\"modelColumnId\":352,\"columnName\":\"student_id\",\"workspaceTableId\":24},\"alias\":\"student_count\"}. "
            "Example addSort: {\"op\":\"addSort\",\"col\":{\"modelColumnId\":700,\"columnName\":\"available_credits\",\"workspaceTableId\":9},\"dir\":\"desc\"}. "
            "Full response example: {\"edits\":[{\"op\":\"setDomain\",\"domainId\":1}],\"explanation\":\"...\",\"confidence\":0.8}. "
            "Only choose domains and columns that are present in provided candidates. "
            "If unsure, return edits=[] and explain what additional information is needed. "
            "Time interpretation rules: "
            "'2023-2024 school year' means school_year = 2024; "
            "'2022-2024' means between 2022 and 2024 inclusive. "
            "When the user prompt contains literal values (names, numbers, strings, booleans, dates, or labeled values like 'first name: Holden'), "
            "you MUST generate addFilter edits. "
            "Returning only addSelect edits when literal constraints are present is incorrect. "
            "Every literal constraint in the user prompt must produce an addFilter edit. "
            "Use operator \"equals\" unless the user specifies otherwise. "
            "For country/state literals, include both full-text and abbreviation values in filtering (for example Mexico and MX, California and CA), preferably with operator \"in\". "
            "For ordinal literals, include both numeric and word variants in filtering (for example 3rd and third, 4th and fourth), preferably with operator \"in\". "
            "For grade-level filters, convert ordinal text to integer values (for example 3rd/third -> 3, 4th/fourth -> 4). "
            "When edits reference any column (via addSelect, addFilter, addGroupBy, addAggregate), "
            "you MUST emit a setDomain edit before any other edits. "
            "The domain must not be null in the final sqlJson. "
            "If multiple domains are candidates, select the best match based on column candidates. "
            "When a column is referenced in a filter (addFilter) and the query is not an aggregation-only query, "
            "you MUST also emit an addSelect edit for that column. "
            "Do not leave the columns list empty when filters reference columns, "
            "unless the user explicitly requests only a count or aggregation. "
            "When the user prompt implies aggregation (e.g., 'how many', 'count', 'total', 'average', 'sum'), "
            "you MUST emit an addAggregate edit. "
            "Do not rely on explanation text. "
            "The aggregation must be represented as a structured addAggregate edit. "
            "If the user asks 'How many', default to count. "
            "Use count_distinct ONLY when the user explicitly asks for distinct or unique values. "
            "If aggregation is present, do not emit unnecessary addSelect edits unless grouping is required. "
            "When the user prompt implies grouping or breakdown by a category (e.g., 'by', 'per', 'for each', 'grouped by', 'breakdown by', 'distribution by'), "
            "you MUST emit addGroupBy edits for the relevant column(s). "
            "When the user prompt implies ordering, ranking, or prioritization (e.g., 'top', 'highest', 'lowest', 'sorted by', 'order by', 'rank', 'most', 'least'), "
            "you MUST emit addSort edits with dir asc|desc. "
            "Do not rely on explanation text for grouping or sorting; emit structured edits explicitly. "
            "When the user asks to show/list/display/give entities (students, schools, courses), "
            "you MUST include at least two projection columns when available. "
            "Include identifier columns such as student_id, first_name, or last_name when available. "
            "Example: User: Find the student first name: Holden, last name: Black. "
            "Correct edits: [{\"op\":\"setDomain\",\"domainId\":6},{\"op\":\"addFilter\",\"col\":{\"modelColumnId\":354,\"columnName\":\"first_name\",\"workspaceTableId\":24},\"operator\":\"equals\",\"value\":\"Holden\"},{\"op\":\"addFilter\",\"col\":{\"modelColumnId\":356,\"columnName\":\"last_name\",\"workspaceTableId\":24},\"operator\":\"equals\",\"value\":\"Black\"}]. "
            "Projection-correct edits example: [{\"op\":\"setDomain\",\"domainId\":6},{\"op\":\"addSelect\",\"col\":{\"modelColumnId\":354,\"columnName\":\"first_name\",\"workspaceTableId\":24},\"alias\":\"first_name\"},{\"op\":\"addSelect\",\"col\":{\"modelColumnId\":356,\"columnName\":\"last_name\",\"workspaceTableId\":24},\"alias\":\"last_name\"},{\"op\":\"addFilter\",\"col\":{\"modelColumnId\":354,\"columnName\":\"first_name\",\"workspaceTableId\":24},\"operator\":\"equals\",\"value\":\"Holden\"},{\"op\":\"addFilter\",\"col\":{\"modelColumnId\":356,\"columnName\":\"last_name\",\"workspaceTableId\":24},\"operator\":\"equals\",\"value\":\"Black\"}]. "
            "Aggregation-correct edits example: [{\"op\":\"setDomain\",\"domainId\":6},{\"op\":\"addFilter\",\"col\":{\"modelColumnId\":354,\"columnName\":\"first_name\",\"workspaceTableId\":24},\"operator\":\"equals\",\"value\":\"Holden\"},{\"op\":\"addAggregate\",\"func\":\"count\",\"col\":{\"modelColumnId\":352,\"columnName\":\"student_id\",\"workspaceTableId\":24},\"alias\":\"student_count\"}]. "
            "Grouping-correct edits example: [{\"op\":\"setDomain\",\"domainId\":6},{\"op\":\"addGroupBy\",\"col\":{\"modelColumnId\":500,\"columnName\":\"race_ethnicity\",\"workspaceTableId\":24}},{\"op\":\"addAggregate\",\"func\":\"count\",\"col\":{\"modelColumnId\":352,\"columnName\":\"student_id\",\"workspaceTableId\":24},\"alias\":\"student_count\"}]. "
            "Sorting-correct edits example: [{\"op\":\"setDomain\",\"domainId\":6},{\"op\":\"addSelect\",\"col\":{\"modelColumnId\":700,\"columnName\":\"available_credits\",\"workspaceTableId\":9},\"alias\":\"available_credits\"},{\"op\":\"addSort\",\"col\":{\"modelColumnId\":700,\"columnName\":\"available_credits\",\"workspaceTableId\":9},\"dir\":\"desc\"}]. "
            "Allowed edit operations are: "
            "setDomain(domainId), addSelect(col, alias), "
            "addFilter(col, operator, value), addGroupBy(col), "
            "addAggregate(func, col, alias), addSort(col, dir). "
            "Allowed filter operators: equals, contains, starts_with, in, gt, lt, between. "
            "Allowed aggregate funcs: count_distinct, count, sum, avg. "
            "Allowed sort directions: asc, desc."
        )

    def _build_user_prompt(self, suggest_request: SuggestRequest) -> str:
        payload = suggest_request.model_dump(mode="json")
        return (
            "Generate planner edits for this request. Respect mode and candidates strictly.\n"
            f"{json.dumps(payload, separators=(',', ':'))}"
        )

    def _build_repair_prompt(self, previous_content: str) -> str:
        truncated = (previous_content or "")[:MAX_REPAIR_PREVIOUS_OUTPUT_CHARS]
        return (
            "Your previous output was invalid. Output ONLY valid JSON, no markdown, no extra text. "
            "Use key 'op' (NOT 'operation') for every edit object. "
            "Use key 'col' (NOT 'columnKey') for addSelect/addFilter/addGroupBy/addAggregate/addSort. "
            "In 'col', include ONLY: modelColumnId, columnName, workspaceTableId, exprId, alias. "
            "Response MUST include top-level keys: edits, explanation, confidence. "
            "Use SqlColumnKey objects under key 'col' for edit fields (NOT string columnKey). "
            "Filter operators must be equals/contains/starts_with/in/gt/lt/between. "
            "Sort direction must be asc or desc. "
            "Previous invalid output (truncated): "
            f"{truncated}"
        )

    def _build_filter_retry_prompt(self) -> str:
        return (
            "You failed to generate required addFilter edits. Every literal constraint must produce an addFilter. Regenerate."
        )

    def _build_domain_retry_prompt(self) -> str:
        return (
            "You did not generate a required setDomain edit. Regenerate and include setDomain."
        )

    def _build_aggregate_retry_prompt(self) -> str:
        return (
            "You did not emit required addAggregate edit. Regenerate including addAggregate."
        )

    def _build_groupby_retry_prompt(self) -> str:
        return (
            "You did not emit required addGroupBy edit. Regenerate including addGroupBy for the grouping intent."
        )

    def _build_projection_completeness_retry_prompt(self) -> str:
        return (
            "You must include at least two projection columns when listing entities. "
            "Include identifier columns such as student_id, first_name, or last_name when available."
        )

    def _infer_domain_safely(self, *, workspace_id: str, edits: list[dict]) -> Optional[int]:
        try:
            inferred = infer_domain_from_columns(
                workspace_id=workspace_id,
                edits=edits,
                sql_executor=self._sql,
            )
            logger.info(
                "AI suggest deterministic domain inference triggered=%s inferred_domain=%s",
                True,
                inferred,
            )
            return inferred
        except Exception as exc:
            logger.warning("AI suggest deterministic domain inference failed: %s", exc)
            return None

    def _seed_sqljson_domain_if_missing(
        self,
        *,
        current_sqljson: Optional[Dict[str, Any]],
        suggest_request: SuggestRequest,
        validated: SuggestModelResponse,
    ) -> Optional[Dict[str, Any]]:
        has_set_domain = any(getattr(edit, "op", "") == "setDomain" for edit in validated.edits)
        if has_set_domain:
            return current_sqljson

        fallback_domain_id = self._fallback_domain_id(suggest_request)
        if fallback_domain_id is None:
            return current_sqljson

        if isinstance(current_sqljson, dict):
            seeded = deepcopy(current_sqljson)
            if seeded.get("domainId") is not None:
                return current_sqljson
            seeded["domainId"] = fallback_domain_id
            logger.info(
                "AI suggest seeded missing domainId from request context domainId=%s",
                fallback_domain_id,
            )
            return seeded

        logger.info(
            "AI suggest seeded missing domainId from request context domainId=%s",
            fallback_domain_id,
        )
        return {"domainId": fallback_domain_id}

    def _fallback_domain_id(self, suggest_request: SuggestRequest) -> Optional[int]:
        domain_context = suggest_request.domainContext
        if domain_context is None:
            return None
        if domain_context.selectedDomainId is not None:
            return int(domain_context.selectedDomainId)
        if len(domain_context.domainCandidates) == 1:
            return int(domain_context.domainCandidates[0].domainId)
        return None

    def _current_sqljson_domain_id(self, current_sqljson: Optional[Dict[str, Any]]) -> Optional[int]:
        if not isinstance(current_sqljson, dict):
            return None
        try:
            domain_id = current_sqljson.get("domainId")
            if domain_id is None:
                return None
            return int(domain_id)
        except (TypeError, ValueError):
            return None

    def _columns_from_filter_tree(self, filter_node: Dict[str, Any]) -> List[Dict[str, Any]]:
        refs: List[Dict[str, Any]] = []
        seen: set[tuple] = set()

        def walk(node: Any) -> None:
            if not isinstance(node, dict):
                return
            node_type = str(node.get("type") or "")
            if node_type == "condition":
                field = node.get("field")
                if isinstance(field, dict) and str(field.get("columnName") or "").strip():
                    identity = _column_ref_identity(field)
                    if identity not in seen:
                        seen.add(identity)
                        refs.append(dict(field))
                return
            children = node.get("children")
            if isinstance(children, list):
                for child in children:
                    walk(child)

        walk(filter_node)
        return [{"field": ref, "alias": ref.get("columnName")} for ref in refs]

    def _normalize_distinct_aggregate_policy(
        self,
        validated: SuggestModelResponse,
        *,
        distinct_requested: bool,
    ) -> tuple[SuggestModelResponse, int]:
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

    def _normalize_geography_filter_aliases(
        self,
        validated: SuggestModelResponse,
    ) -> tuple[SuggestModelResponse, int]:
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
                seen: set[str] = set()
                for item in merged:
                    if isinstance(item, str):
                        key = item.lower()
                        if key in seen:
                            continue
                        seen.add(key)
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

    def _order_setdomain_first(self, edits: List[Any]) -> List[Any]:
        set_domain_edits = [edit for edit in edits if getattr(edit, "op", "") == "setDomain"]
        if not set_domain_edits:
            return list(edits)
        non_domain_edits = [edit for edit in edits if getattr(edit, "op", "") != "setDomain"]
        return [*set_domain_edits, *non_domain_edits]

    def _enforce_sqljson_aggs_from_edits(self, sqljson: Dict[str, Any], edits: list[dict]) -> None:
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

    def _enforce_sqljson_sorting_from_edits(self, sqljson: Dict[str, Any], edits: list[dict]) -> None:
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

    def _log_raw_model_output(self, attempt: int, content: str) -> None:
        if len(content) <= MAX_RAW_MODEL_LOG_CHARS:
            logger.info("AI suggest raw model output attempt=%s content=%s", attempt, content)
            return
        logger.info(
            "AI suggest raw model output attempt=%s content=%s...[truncated %s chars]",
            attempt,
            content[:MAX_RAW_MODEL_LOG_CHARS],
            len(content) - MAX_RAW_MODEL_LOG_CHARS,
        )

    def _normalize_model_payload(self, payload: Any) -> tuple[Any, Dict[str, int]]:
        meta = {"rewritten_ops": 0, "dropped_edits": 0}
        if not isinstance(payload, dict):
            return payload, meta

        payload.setdefault("edits", [])
        payload.setdefault("explanation", "")
        payload.setdefault("confidence", 0.5)

        explanation = payload.get("explanation")
        if not isinstance(explanation, str):
            payload["explanation"] = str(explanation)

        confidence_raw = payload.get("confidence", 0.5)
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            confidence = 0.5
        payload["confidence"] = max(0.0, min(1.0, confidence))

        edits = payload.get("edits")
        if not isinstance(edits, list):
            return payload, meta

        normalized_edits: List[Dict[str, Any]] = []
        for edit in edits:
            if not isinstance(edit, dict):
                meta["dropped_edits"] += 1
                continue

            if "op" not in edit and "operation" in edit:
                edit["op"] = edit.pop("operation")
                meta["rewritten_ops"] += 1
            elif "op" not in edit and "action" in edit:
                edit["op"] = edit.pop("action")
                meta["rewritten_ops"] += 1

            op = edit.get("op")
            if op not in ALLOWED_EDIT_OPS:
                meta["dropped_edits"] += 1
                continue

            drop_edit = self._normalize_edit_column_shape(edit)
            if drop_edit:
                meta["dropped_edits"] += 1
                continue
            if op == "addFilter":
                raw_operator = edit.get("operator")
                if isinstance(raw_operator, str) and raw_operator in LEGACY_FILTER_OPERATOR_MAP:
                    edit["operator"] = LEGACY_FILTER_OPERATOR_MAP[raw_operator]
            elif op == "addSort":
                if "dir" not in edit and "direction" in edit:
                    edit["dir"] = edit.pop("direction")
                raw_dir = edit.get("dir")
                if isinstance(raw_dir, str):
                    dir_lc = raw_dir.lower()
                    if dir_lc == "descending":
                        dir_lc = "desc"
                    elif dir_lc == "ascending":
                        dir_lc = "asc"
                    edit["dir"] = dir_lc

            normalized_edits.append(edit)

        payload["edits"] = normalized_edits

        if meta["rewritten_ops"] or meta["dropped_edits"]:
            logger.info(
                "AI suggest normalization rewrote_ops=%s dropped_edits=%s",
                meta["rewritten_ops"],
                meta["dropped_edits"],
            )
        return payload, meta

    def _normalize_edit_column_shape(self, edit: Dict[str, Any]) -> bool:
        if "col" in edit:
            if isinstance(edit["col"], dict):
                edit["col"] = _sanitize_col(edit["col"])
                if "columnName" not in edit["col"]:
                    return True
                self._ensure_sql_column_key_defaults(edit["col"])
            return False

        alias_value = None
        for alias in ("columnKey", "field", "column"):
            if alias in edit:
                alias_value = edit.pop(alias)
                break

        if isinstance(alias_value, dict):
            edit["col"] = _sanitize_col(alias_value)
            if "columnName" not in edit["col"]:
                return True
            self._ensure_sql_column_key_defaults(edit["col"])
            return False
        if isinstance(alias_value, str) and alias_value.strip():
            edit["col"] = self._sql_column_key_from_legacy_string(alias_value)
            return False
        if alias_value is not None:
            edit["col"] = alias_value
            return False
        return False

    def _sql_column_key_from_legacy_string(self, value: str) -> Dict[str, Any]:
        text = value.strip()
        column_name = text.split(".")[-1] if "." in text else text
        return {
            "modelColumnId": None,
            "columnName": column_name,
            "workspaceTableId": None,
            "exprId": None,
            "alias": None,
        }

    def _ensure_sql_column_key_defaults(self, key: Dict[str, Any]) -> None:
        key.setdefault("modelColumnId", None)
        key.setdefault("workspaceTableId", None)
        key.setdefault("exprId", None)
        key.setdefault("alias", None)

    def _enforce_grounding(
        self,
        *,
        validated: SuggestModelResponse,
        valid_domain_ids: Optional[set[int]],
        valid_column_keys: Optional[set[str]],
    ) -> tuple[SuggestModelResponse, int]:
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

    def _column_signature(self, col: SqlColumnKey) -> str:
        return "|".join(
            [
                str(col.workspaceTableId),
                (col.columnName or "").strip().lower(),
            ]
        )
