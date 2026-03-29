from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

from app.services.forge_match.field_extractor import SourceFieldRecord
from app.services.forge_match.normalizer import token_overlap_score, token_set, type_compatibility


class ForgeMatchConfidenceScorer:
    def score(
        self,
        *,
        source_record: SourceFieldRecord,
        selected_candidate: Optional[Dict[str, Any]],
        candidates: Sequence[Dict[str, Any]],
        llm_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        if selected_candidate is None:
            base = 25.0 if str(llm_result.get("match_decision") or "") == "ambiguous" else 5.0
            score = int(round(max(0.0, min(100.0, base))))
            return {
                "confidence_score": score,
                "confidence_band": _band(score),
            }

        lexical = float(selected_candidate.get("lexical_score") or 0.0)
        vector = float(selected_candidate.get("vector_score") or 0.0)
        retrieval = float(selected_candidate.get("combined_retrieval_score") or 0.0)
        dtype = type_compatibility(source_record.source_type, selected_candidate.get("data_type"))

        desc_sim = token_overlap_score(
            token_set(source_record.source_description),
            token_set(selected_candidate.get("description")),
        )
        table_align = token_overlap_score(
            token_set(source_record.source_object_name),
            token_set(selected_candidate.get("table_name"), selected_candidate.get("domain_name")),
        )

        llm_conf = float(llm_result.get("llm_confidence") or 0.0)
        llm_conf = max(0.0, min(1.0, llm_conf))

        score_norm = (
            (lexical * 0.24)
            + (vector * 0.24)
            + (retrieval * 0.18)
            + (dtype * 0.12)
            + (desc_sim * 0.08)
            + (table_align * 0.06)
            + (llm_conf * 0.08)
        )

        # Penalize close second-best candidates to reflect ambiguity.
        ambiguity_penalty = self._ambiguity_penalty(candidates=candidates)
        if str(llm_result.get("match_decision") or "") == "ambiguous":
            ambiguity_penalty += 0.10
        if str(llm_result.get("match_decision") or "") == "no_confident_match":
            ambiguity_penalty += 0.25

        score_norm = max(0.0, min(1.0, score_norm - ambiguity_penalty))
        score = int(round(score_norm * 100.0))
        return {
            "confidence_score": score,
            "confidence_band": _band(score),
        }

    @staticmethod
    def _ambiguity_penalty(*, candidates: Sequence[Dict[str, Any]]) -> float:
        if len(candidates) < 2:
            return 0.0
        ranked = sorted(candidates, key=lambda row: float(row.get("combined_retrieval_score") or 0.0), reverse=True)
        top = float(ranked[0].get("combined_retrieval_score") or 0.0)
        second = float(ranked[1].get("combined_retrieval_score") or 0.0)
        gap = max(0.0, top - second)
        if gap >= 0.25:
            return 0.0
        if gap >= 0.12:
            return 0.05
        if gap >= 0.06:
            return 0.10
        return 0.18


def _band(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


__all__ = ["ForgeMatchConfidenceScorer"]
