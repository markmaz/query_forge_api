from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.services.semantic.semantic_llm_schema import normalize_concept_key


class SemanticConceptMatcher:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def load_known_concepts(self, vertical_norm: str) -> List[Dict[str, Any]]:
        vertical = _norm_vertical(vertical_norm)
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              id,
              vertical_norm,
              concept_key,
              semantic_type,
              sub_type,
              entity,
              description,
              granularity_rank,
              filter_allowed,
              group_by_allowed,
              aggregation_allowed,
              is_identifier,
              is_metric,
              display_priority,
              `sensitive` AS `sensitive`
            FROM semantic_concept
            WHERE `status` = 'active'
              AND vertical_norm IN (:vertical, 'generic')
            ORDER BY CASE WHEN vertical_norm = :vertical THEN 0 ELSE 1 END, concept_key
            """,
            {"vertical": vertical},
        )
        out: List[Dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            concept_key = normalize_concept_key(item.get("concept_key") or "")
            if not concept_key:
                continue
            item["concept_key"] = concept_key
            if item.get("id") is not None:
                item["id"] = int(item["id"])
            out.append(item)
        return out

    def load_alias_rules(self, vertical_norm: str) -> List[Dict[str, Any]]:
        vertical = _norm_vertical(vertical_norm)
        return self._sql.execute_query_mappings(
            """
            SELECT alias_key, concept_key, match_kind, weight, vertical_norm
            FROM semantic_concept_alias
            WHERE vertical_norm IN (:vertical, 'generic')
            ORDER BY CASE WHEN vertical_norm = :vertical THEN 0 ELSE 1 END, weight DESC, id ASC
            """,
            {"vertical": vertical},
        )

    def match_by_alias(
        self,
        card: Dict[str, Any],
        *,
        vertical_norm: str,
        alias_rules: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[Optional[Dict[str, Any]], List[str]]:
        col = str(card.get("columnName") or "").strip().lower()
        if not col:
            return None, []

        rows = alias_rules if alias_rules is not None else self.load_alias_rules(vertical_norm)

        best_candidate: Optional[Dict[str, Any]] = None
        best_score = -1.0
        best_note = ""
        normalized_col = _normalize_alias_text(col)

        for row in rows:
            alias = str(row.get("alias_key") or "").strip().lower()
            concept_key_raw = str(row.get("concept_key") or "")
            concept_key = normalize_concept_key(concept_key_raw)
            match_kind = str(row.get("match_kind") or "exact").strip().lower()
            try:
                weight = float(row.get("weight") or 0.0)
            except Exception:
                weight = 0.0

            matched = False
            regex_match: Optional[re.Match[str]] = None
            if match_kind == "exact":
                matched = col == alias
                bonus = 0.25
            elif match_kind == "normalized":
                matched = normalized_col == _normalize_alias_text(alias)
                bonus = 0.2
            elif match_kind == "prefix":
                matched = normalized_col.startswith(_normalize_alias_text(alias))
                bonus = 0.15
            elif match_kind == "suffix":
                matched = normalized_col.endswith(_normalize_alias_text(alias))
                bonus = 0.15
            elif match_kind == "contains":
                matched = alias in col
                bonus = 0.12
            elif match_kind == "regex":
                try:
                    regex_match = re.search(alias, col)
                    matched = regex_match is not None
                except re.error:
                    matched = False
                    regex_match = None
                bonus = 0.1
            else:
                bonus = 0.0

            resolved_key = concept_key
            if matched and match_kind == "regex" and regex_match is not None:
                dynamic_key = self._dynamic_concept_from_regex(alias, regex_match, col)
                if dynamic_key:
                    resolved_key = dynamic_key

            score = max(0.0, min(1.0, weight + bonus))
            if matched and resolved_key and score > best_score:
                best_candidate = {
                    "concept_key": resolved_key,
                    "confidence": score,
                }
                best_score = score
                best_note = f"alias_match:{match_kind}:{alias}"

        if best_candidate:
            return best_candidate, [best_note]
        return None, []

    def resolve_pre_llm(
        self,
        *,
        card: Dict[str, Any],
        vertical_norm: str,
        known_concepts: Optional[List[Dict[str, Any]]] = None,
        alias_rules: Optional[List[Dict[str, Any]]] = None,
        alias_conf_threshold: float = 0.75,
    ) -> Tuple[Optional[Dict[str, Any]], List[str]]:
        # Priority order: deterministic > alias(weighted) > llm > fallback.
        deterministic, det_notes = self._deterministic_identifier_candidate(card=card)
        if deterministic is not None:
            return deterministic, det_notes

        alias_candidate, alias_notes = self.match_by_alias(
            card=card,
            vertical_norm=vertical_norm,
            alias_rules=alias_rules,
        )
        if alias_candidate and float(alias_candidate.get("confidence") or 0.0) >= float(alias_conf_threshold):
            key = normalize_concept_key(alias_candidate.get("concept_key") or "")
            concept_source = "alias" if key else "fallback"
            proposal = {
                "concept_key": key,
                "concept_source": concept_source,
                "canonical_match_confidence": float(alias_candidate.get("confidence") or 0.0),
                "semantic_type": "identifier" if key.endswith("_ID") or "CODE" in key else "attribute",
                "sub_type": None,
                "entity": _infer_entity_from_key(key),
                "granularity_rank": 0,
                "filter_allowed": True,
                "group_by_allowed": True,
                "aggregation_allowed": False if key.endswith("_ID") else True,
                "is_identifier": True if key.endswith("_ID") or "CODE" in key else False,
                "is_metric": False,
                "display_priority": 0,
                "sensitive": False,
                "confidence": float(alias_candidate.get("confidence") or 0.0),
                "reasons": [
                    f"alias_match:{str(card.get('columnName') or '').strip().lower()}->{key}",
                    "column_name_evidence",
                ],
            }
            return proposal, alias_notes

        return None, det_notes + alias_notes

    def match_by_heuristics(self, card: Dict[str, Any], *, vertical_norm: str) -> Tuple[Optional[str], List[str]]:
        vertical = _norm_vertical(vertical_norm)
        col = str(card.get("columnName") or "").strip().lower()
        desc = str(card.get("description") or "").strip().lower()
        samples = card.get("samples") if isinstance(card.get("samples"), list) else []

        if vertical == "education":
            if col == "k_student" or (_contains(col, "student") and _has_any(col, ["id", "key"])):
                return "STUDENT_ID", ["heuristic_match:student_id"]
            if col == "k_school" or (_contains(col, "school") and _has_any(col, ["id", "key"])):
                return "SCHOOL_ID", ["heuristic_match:school_id"]
            if col == "k_lea" or ((_contains(col, "lea") or _contains(col, "district")) and _has_any(col, ["id", "key"])):
                return "LEA_ID", ["heuristic_match:lea_id"]
            if col == "k_course" or (_contains(col, "course") and _has_any(col, ["id", "key"])):
                return "COURSE_ID", ["heuristic_match:course_id"]
            if _contains(col, "section") and _has_any(col, ["id", "key"]):
                return "SECTION_ID", ["heuristic_match:section_id"]
            if _contains(col, "school_year") or (_samples_are_year(samples) and "academic year" in desc):
                return "SCHOOL_YEAR", ["heuristic_match:school_year"]
            if _contains(col, "county"):
                return "COUNTY", ["heuristic_match:county"]
            if _contains(col, "city"):
                return "CITY", ["heuristic_match:city"]
            if _contains(col, "zip") or _contains(col, "postal"):
                return "ZIP_CODE", ["heuristic_match:zip_code"]
            if _contains(col, "state_course_code"):
                return "STATE_COURSE_CODE", ["heuristic_match:state_course_code"]

        return None, []

    def enforce_canonical_if_strong(
        self,
        card: Dict[str, Any],
        proposal: Dict[str, Any],
        vertical_norm: str,
        known_concepts: Optional[List[Dict[str, Any]]] = None,
        alias_rules: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[Dict[str, Any], List[str]]:
        out = dict(proposal)
        notes: List[str] = []

        deterministic, det_notes = self._deterministic_identifier_candidate(card=card)
        if deterministic is not None:
            out.update(deterministic)
            notes.extend(det_notes)
            return out, notes

        alias_candidate, alias_notes = self.match_by_alias(
            card,
            vertical_norm=vertical_norm,
            alias_rules=alias_rules,
        )
        if alias_candidate:
            alias_key = normalize_concept_key(alias_candidate.get("concept_key") or "")
            out["concept_key"] = alias_key
            out["concept_source"] = "alias"
            out["canonical_match_confidence"] = max(
                _clamp_float(out.get("canonical_match_confidence")),
                _clamp_float(alias_candidate.get("confidence")),
            )
            out["confidence"] = max(_clamp_float(out.get("confidence")), _clamp_float(alias_candidate.get("confidence")), 0.85)
            source_col = normalize_concept_key(card.get("columnName") or "")
            out["reasons"] = [
                f"alias_match:{source_col.lower()}->{alias_key}",
                "column_name_evidence",
            ]
            notes.extend(alias_notes)
            return out, notes

        known = known_concepts if known_concepts is not None else self.load_known_concepts(vertical_norm)
        known_map = {normalize_concept_key(c["concept_key"]): c for c in known}

        heuristic_key, heuristic_notes = self.match_by_heuristics(card, vertical_norm=vertical_norm)
        if heuristic_key and heuristic_key in known_map:
            out["concept_key"] = heuristic_key
            out["concept_source"] = "deterministic"
            out["canonical_match_confidence"] = max(_clamp_float(out.get("canonical_match_confidence")), 0.85)
            notes.extend(heuristic_notes)
            return out, notes

        concept_source = str(out.get("concept_source") or "fallback").strip().lower()
        concept_key = normalize_concept_key(out.get("concept_key") or "")

        if concept_source == "canonical" and concept_key in known_map:
            out["concept_key"] = concept_key
            out["concept_source"] = "llm"
            out["canonical_match_confidence"] = max(_clamp_float(out.get("canonical_match_confidence")), 0.7)
            return out, notes

        if concept_source == "canonical" and concept_key not in known_map:
            notes.append("llm_canonical_unknown_flipped_to_fallback")

        if concept_key in known_map:
            out["concept_key"] = concept_key
            out["concept_source"] = "llm"
            out["canonical_match_confidence"] = max(_clamp_float(out.get("canonical_match_confidence")), 0.65)
            return out, notes

        fallback_key = normalize_concept_key(card.get("columnName") or concept_key)
        out["concept_key"] = fallback_key
        out["concept_source"] = "fallback"
        out["canonical_match_confidence"] = _clamp_float(out.get("canonical_match_confidence"))
        return out, notes

    def _deterministic_identifier_candidate(self, *, card: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[str]]:
        col_raw = str(card.get("columnName") or "").strip()
        col = col_raw.lower()
        if col == "":
            return None, []

        key: Optional[str] = None
        reasons: List[str] = []
        if "tenant" in col:
            key = "TENANT_CODE"
            reasons.append("column_name_contains_tenant")
        elif col.startswith("k_"):
            if col == "k_lea" or "lea" in col:
                key = "LEA_ID"
            elif col == "k_school" or "school" in col:
                key = "SCHOOL_ID"
            elif col == "k_student":
                key = "STUDENT_ID"
            else:
                entity = col[2:].strip("_")
                entity_key = normalize_concept_key(entity) or "ENTITY"
                key = f"{entity_key}_ID"
            reasons.append("column_name_prefix_k_")
        elif col.endswith("_id"):
            key = normalize_concept_key(col)
            reasons.append("column_name_suffix__id")

        if not key:
            return None, []

        proposal = {
            "concept_key": key,
            "concept_source": "deterministic",
            "canonical_match_confidence": 0.97,
            "semantic_type": "identifier",
            "sub_type": None,
            "entity": _infer_entity_from_key(key),
            "granularity_rank": 0,
            "filter_allowed": True,
            "group_by_allowed": True,
            "aggregation_allowed": False,
            "is_identifier": True,
            "is_metric": False,
            "display_priority": 0,
            "sensitive": False,
            "confidence": 0.97,
            "reasons": reasons[:2] or ["deterministic_identifier_rule"],
        }
        return proposal, ["deterministic_identifier_match"]

    def _dynamic_concept_from_regex(self, pattern: str, match: re.Match[str], col: str) -> Optional[str]:
        if pattern == r"^k_(.+)$":
            captured = str(match.group(1) or "").strip().lower()
            if captured == "":
                return None
            if "lea" in captured:
                return "LEA_ID"
            if "school" in captured:
                return "SCHOOL_ID"
            if "student" in captured:
                return "STUDENT_ID"
            return f"{normalize_concept_key(captured) or 'ENTITY'}_ID"
        if pattern == r"^(.+)_id$":
            captured = str(match.group(1) or "").strip()
            if captured == "":
                return None
            return f"{normalize_concept_key(captured)}_ID"
        if "tenant" in col:
            return "TENANT_CODE"
        return None


def _norm_vertical(vertical_norm: str) -> str:
    value = str(vertical_norm or "generic").strip().lower()
    return value or "generic"


def _contains(text: str, needle: str) -> bool:
    return needle in text


def _has_any(text: str, tokens: List[str]) -> bool:
    return any(token in text for token in tokens)


def _samples_are_year(samples: List[Any]) -> bool:
    vals = [str(v).strip() for v in samples if v is not None and str(v).strip() != ""]
    if not vals:
        return False
    return all(re.fullmatch(r"\d{4}", val) is not None for val in vals)


def _clamp_float(value: Any) -> float:
    try:
        out = float(value)
    except Exception:
        out = 0.0
    return max(0.0, min(1.0, out))


def _normalize_alias_text(value: str) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def _infer_entity_from_key(concept_key: str) -> Optional[str]:
    key = normalize_concept_key(concept_key)
    if key.endswith("_ID"):
        base = key[: -3]
        if base:
            return base.lower()
    return None
