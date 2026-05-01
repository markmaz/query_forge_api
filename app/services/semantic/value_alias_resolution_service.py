from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort
from app.services.feedback_learning.runtime_override_resolver import (
    RuntimeOverrideResolver,
)


class ValueAliasResolutionService:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        runtime_override_resolver: Optional[RuntimeOverrideResolver] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._runtime_override_resolver = runtime_override_resolver

    def resolve(self, *, prompt: str, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        ngrams = _build_ngrams(prompt)
        if not ngrams:
            return []

        candidates: List[Dict[str, Any]] = []
        for ngram in ngrams:
            rows = self._sql.execute_query_mappings(
                """
                SELECT
                  sc.concept_key,
                  va.semantic_concept_id,
                  va.canonical_value,
                  va.alias_value,
                  va.match_kind,
                  va.weight
                FROM semantic_value_alias va
                JOIN semantic_concept sc
                  ON sc.id = va.semantic_concept_id
                WHERE (
                    (va.match_kind = 'exact' AND LOWER(va.alias_value) = :ngram)
                    OR
                    (va.match_kind = 'contains' AND :ngram LIKE CONCAT('%', LOWER(va.alias_value), '%'))
                  )
                ORDER BY
                  va.weight DESC,
                  va.id ASC
                """,
                {"ngram": ngram},
            )
            for row in rows:
                concept_key = str(row.get("concept_key") or "").strip().upper()
                canonical_value = str(row.get("canonical_value") or "").strip()
                alias_value = str(row.get("alias_value") or "").strip()
                if concept_key == "" or canonical_value == "" or alias_value == "":
                    continue
                candidates.append(
                    {
                        "concept_key": concept_key,
                        "semantic_concept_id": _to_int_or_none(row.get("semantic_concept_id")),
                        "canonical_value": canonical_value,
                        "matched_alias": alias_value,
                        "matched_ngram": ngram,
                        "match_kind": str(row.get("match_kind") or "").strip().lower() or "contains",
                        "weight": _to_float(row.get("weight")) or 0.0,
                    }
                )

        if self._runtime_override_resolver is not None:
            for row in self._runtime_override_resolver.resolve_prompt_alias_rows(
                prompt=prompt,
                workspace_id=workspace_id,
            ):
                concept_key = str(row.get("concept_key") or "").strip().upper()
                canonical_value = str(row.get("canonical_value") or "").strip()
                alias_value = str(row.get("alias_value") or "").strip()
                if concept_key == "" or canonical_value == "" or alias_value == "":
                    continue
                candidates.append(
                    {
                        "concept_key": concept_key,
                        "semantic_concept_id": _to_int_or_none(
                            row.get("semantic_concept_id")
                        ),
                        "canonical_value": canonical_value,
                        "matched_alias": alias_value,
                        "matched_ngram": str(row.get("matched_ngram") or alias_value),
                        "match_kind": str(row.get("match_kind") or "").strip().lower()
                        or "contains",
                        "weight": _to_float(row.get("weight")) or 0.0,
                    }
                )

        return _dedupe_by_concept(candidates)


def _build_ngrams(prompt: str) -> List[str]:
    text = str(prompt or "").lower()
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    tokens = [tok for tok in text.split() if tok]
    out: List[str] = []
    for n in (3, 2, 1):
        for idx in range(0, max(0, len(tokens) - n + 1)):
            out.append(" ".join(tokens[idx : idx + n]))
    return list(dict.fromkeys(out))


def _dedupe_by_concept(candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    best: Dict[str, Dict[str, Any]] = {}
    for item in candidates:
        concept_key = str(item.get("concept_key") or "").strip().upper()
        if concept_key == "":
            continue
        current = best.get(concept_key)
        if current is None or _rank_tuple(item) > _rank_tuple(current):
            best[concept_key] = dict(item)
    return sorted(best.values(), key=lambda row: (-float(row.get("weight") or 0.0), row.get("concept_key") or ""))


def _rank_tuple(item: Dict[str, Any]) -> Tuple[float, int, int]:
    weight = float(item.get("weight") or 0.0)
    matched_ngram = str(item.get("matched_ngram") or "")
    match_kind = str(item.get("match_kind") or "").lower()
    exact_bonus = 1 if match_kind == "exact" else 0
    return (weight, len(matched_ngram), exact_bonus)


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = ["ValueAliasResolutionService"]
