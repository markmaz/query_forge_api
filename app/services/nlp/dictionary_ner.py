from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import spacy
from spacy.language import Language
from spacy.pipeline import EntityRuler
from spacy.tokens import Doc

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort

LABEL_CONCEPT = "ED_CONCEPT"

INTENT_LIST = ("available", "offered", "catalog")
INTENT_COUNT = ("how many", "count", "number of")
ENTITY_COURSE = ("course", "courses", "class", "classes", "section")

NEGATION_TOKENS = {"not", "no", "non", "without"}


@dataclass(frozen=True)
class ColumnInfo:
    column_name: str
    description: str | None
    model_table_name: str | None
    table_name: str | None = None
    source_table_name: str | None = None


@dataclass(frozen=True)
class ConceptSpec:
    concept: str
    column_candidates: Tuple[str, ...]
    synonyms: Tuple[str, ...]


CONCEPT_SPECS: Tuple[ConceptSpec, ...] = (
    ConceptSpec(
        concept="TERM_FALL",
        column_candidates=("is_fall",),
        synonyms=("fall", "fall semester", "fall term"),
    ),
    ConceptSpec(
        concept="TERM_SPRING",
        column_candidates=("is_spring",),
        synonyms=("spring", "spring semester", "spring term"),
    ),
    ConceptSpec(
        concept="TERM_YEAR_LONG",
        column_candidates=("is_year_long", "is_yearlong", "is_full_year"),
        synonyms=("year long", "year-long", "full year", "full-year"),
    ),
    ConceptSpec(
        concept="COURSE_AP",
        column_candidates=("is_ap", "is_advanced_placement"),
        synonyms=("ap", "advanced placement"),
    ),
    ConceptSpec(
        concept="COURSE_HONORS",
        column_candidates=("is_honors", "is_honour"),
        synonyms=("honors", "honours"),
    ),
    ConceptSpec(
        concept="COURSE_DUAL_CREDIT",
        column_candidates=("is_dual_credit",),
        synonyms=("dual credit",),
    ),
    ConceptSpec(
        concept="COURSE_CTE",
        column_candidates=("is_cte", "is_career_technical", "is_career_tech"),
        synonyms=("cte", "career technical", "career tech"),
    ),
    ConceptSpec(
        concept="COURSE_IB",
        column_candidates=("is_ib", "is_international_baccalaureate"),
        synonyms=("ib", "international baccalaureate"),
    ),
    ConceptSpec(
        concept="COURSE_DISTANCE_LEARNING",
        column_candidates=("is_distance_learning", "is_online"),
        synonyms=("distance learning", "online"),
    ),
    ConceptSpec(
        concept="COURSE_CORE",
        column_candidates=("is_core_subject", "is_core"),
        synonyms=("core", "core subject"),
    ),
    ConceptSpec(
        concept="COURSE_REMEDIAL",
        column_candidates=("is_remedial",),
        synonyms=("remedial",),
    ),
    ConceptSpec(
        concept="COURSE_ADVANCED",
        column_candidates=("is_advanced",),
        synonyms=("advanced",),
    ),
    ConceptSpec(
        concept="COURSE_BASIC",
        column_candidates=("is_basic",),
        synonyms=("basic",),
    ),
    ConceptSpec(
        concept="COURSE_ELL",
        column_candidates=(
            "is_ell",
            "is_ell_active",
            "is_english_learner_active",
            "is_enlglish_learner_active",
        ),
        synonyms=("ell", "el", "english learner"),
    ),
    ConceptSpec(
        concept="COURSE_SWD",
        column_candidates=("is_swd", "is_special_ed", "is_special_education"),
        synonyms=("swd", "students with disabilities", "special education"),
    ),
)


@lru_cache(maxsize=64)
def build_nlp(workspace_id: str, domain_id: int) -> Language:
    columns = _load_domain_columns(workspace_id, domain_id)
    concept_map, concept_phrases = _build_concept_maps(columns)

    nlp = spacy.blank("en")
    ruler: EntityRuler = nlp.add_pipe("entity_ruler", config={"phrase_matcher_attr": "LOWER"})
    patterns = _build_patterns(concept_phrases)
    if patterns:
        ruler.add_patterns(patterns)

    nlp.meta["concept_map"] = concept_map
    return nlp


def extract_signals(workspace_id: str, domain_id: int, text: str) -> Dict[str, Any]:
    text_val = text or ""
    nlp = build_nlp(workspace_id, int(domain_id))
    doc = nlp(text_val)

    intent = _infer_intent(text_val)
    entity = "course" if _contains_any(text_val, ENTITY_COURSE) else None

    concept_map: Dict[str, str] = nlp.meta.get("concept_map", {})
    filters: List[Dict[str, Any]] = []
    seen = set()
    debug_concepts: List[Dict[str, Any]] = []

    for ent in doc.ents:
        if ent.label_ != LABEL_CONCEPT:
            continue
        concept = ent.ent_id_ or ent.text
        debug_concepts.append({"label": LABEL_CONCEPT, "text": ent.text, "concept": concept})
        column_key = concept_map.get(concept)
        if not column_key:
            continue
        value = not _is_negated(doc, ent.start)
        _add_filter(filters, seen, column_key, value)

    return {
        "text": text_val,
        "intent": intent,
        "entity": entity,
        "filters": filters,
        "debug": {"concepts": debug_concepts},
    }


def resolve_column_keys_to_workspace_columns(
    workspace_id: str,
    domain_id: int,
    column_keys: Sequence[str],
    *,
    sql: Optional[ForgeQueryPort] = None,
) -> Dict[str, List[int]]:
    if not column_keys:
        return {}

    executor = sql or ForgeMetaSQL()
    placeholders = ", ".join([f":col_{idx}" for idx in range(len(column_keys))])
    params: Dict[str, Any] = {"workspace_id": workspace_id, "domain_id": int(domain_id)}
    for idx, col in enumerate(column_keys):
        params[f"col_{idx}"] = col

    sql_text = f"""
    SELECT
      wc.column_name AS column_key,
      wc.id AS workspace_column_id
    FROM domain_workspace_table dwt
    JOIN workspace_table wt
      ON wt.id = dwt.workspace_table_id
    JOIN workspace_column wc
      ON wc.workspace_table_id = wt.id
    WHERE wt.workspace_id = :workspace_id
      AND dwt.domain_id = :domain_id
      AND wc.column_name IN ({placeholders})
    ORDER BY wc.column_name, wc.id
    """

    rows = executor.execute_query_mappings(sql_text, params)
    result: Dict[str, List[int]] = {key: [] for key in column_keys}
    for row in rows:
        key = row.get("column_key")
        if key in result and row.get("workspace_column_id") is not None:
            result[key].append(int(row["workspace_column_id"]))
    return result


def _infer_intent(text: str) -> Optional[str]:
    if _contains_any(text, INTENT_COUNT):
        return "COUNT"
    if _contains_any(text, INTENT_LIST):
        return "LIST"
    return None


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    value = text.lower()
    return any(needle in value for needle in needles)


def _add_filter(filters: List[Dict[str, Any]], seen: set, column_key: str, value: Any) -> None:
    key = (column_key, "=", value)
    if key in seen:
        return
    seen.add(key)
    filters.append({"column_key": column_key, "op": "=", "value": value})


def _build_patterns(concept_phrases: Mapping[str, Sequence[str]]) -> List[Dict[str, Any]]:
    patterns: List[Dict[str, Any]] = []
    for concept, phrases in concept_phrases.items():
        for phrase in phrases:
            if not phrase:
                continue
            patterns.append({"label": LABEL_CONCEPT, "id": concept, "pattern": phrase})
    return patterns


def _build_concept_maps(
    columns: Sequence[ColumnInfo],
) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    column_by_name = {c.column_name: c for c in columns}
    column_names = set(column_by_name.keys())
    concept_map: Dict[str, str] = {}
    concept_phrases: Dict[str, List[str]] = {}

    for spec in CONCEPT_SPECS:
        column_key = _resolve_column_key(column_names, spec, column_by_name)
        if not column_key:
            continue
        concept_map[spec.concept] = column_key
        phrases = set(_normalize_phrase(p) for p in spec.synonyms if p)
        phrases.update(_column_name_phrases(column_key))
        column_info = column_by_name.get(column_key)
        if column_info and column_info.description:
            phrases.update(_description_phrases(column_info.description, spec.synonyms))
        concept_phrases[spec.concept] = sorted(p for p in phrases if p)

    return concept_map, concept_phrases


def _resolve_column_key(
    column_names: set,
    spec: ConceptSpec,
    column_by_name: Mapping[str, ColumnInfo],
) -> Optional[str]:
    for candidate in spec.column_candidates:
        if candidate in column_names:
            return candidate

    # Fallback: try to match synonyms against column descriptions/names
    for column_name, info in column_by_name.items():
        haystack = " ".join(
            [
                column_name.replace("_", " ").lower(),
                (info.description or "").lower(),
            ]
        )
        for phrase in spec.synonyms:
            if phrase and phrase.lower() in haystack:
                return column_name
    return None


def _column_name_phrases(column_name: str) -> List[str]:
    tokens = [t for t in column_name.lower().split("_") if t]
    if tokens and tokens[0] in {"is", "has"}:
        tokens = tokens[1:]
    if tokens and tokens[-1] in {"flag", "active"}:
        tokens = tokens[:-1]
    if not tokens:
        return []
    return [" ".join(tokens)]


def _description_phrases(description: str, synonyms: Sequence[str]) -> List[str]:
    phrases: set[str] = set()
    text = description or ""
    lower = text.lower()
    for phrase in synonyms:
        if phrase and phrase.lower() in lower:
            phrases.add(_normalize_phrase(phrase))
    for match in re.findall(r"\b[A-Z]{2,5}\b", text):
        phrases.add(match.lower())
    return list(phrases)


def _normalize_phrase(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _is_negated(doc: Doc, start_token: int, window: int = 3) -> bool:
    start = max(0, start_token - window)
    for tok in doc[start:start_token]:
        if tok.lower_ in NEGATION_TOKENS:
            return True
        if tok.lower_.startswith("non") and len(tok.lower_) > 3:
            return True
    return False


@lru_cache(maxsize=64)
def _load_domain_columns(workspace_id: str, domain_id: int) -> Tuple[ColumnInfo, ...]:
    sql = """
    SELECT DISTINCT
      wc.column_name,
      wc.description,
      COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name) AS table_name,
      wt.full_name AS source_table_name
    FROM domain_workspace_table dwt
    JOIN workspace_table wt
      ON wt.id = dwt.workspace_table_id
    JOIN workspace_column wc
      ON wc.workspace_table_id = wt.id
    WHERE wt.workspace_id = :workspace_id
      AND dwt.domain_id = :domain_id
      AND wt.exists_in_dbx = 1
      AND wc.exists_in_dbx = 1
      AND (wc.is_missing_in_source = 0 OR wc.is_missing_in_source IS NULL)
      AND (wc.is_active = 1 OR wc.is_active IS NULL)
    ORDER BY wc.column_name
    """
    rows = ForgeMetaSQL().execute_query_mappings(
        sql,
        {"workspace_id": workspace_id, "domain_id": int(domain_id)},
    )
    return tuple(
        ColumnInfo(
            column_name=row.get("column_name") or "",
            description=row.get("description"),
            model_table_name=row.get("table_name"),
            table_name=row.get("table_name"),
            source_table_name=row.get("source_table_name"),
        )
        for row in rows
        if row.get("column_name")
    )
