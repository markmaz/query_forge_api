from __future__ import annotations

from typing import Any, Dict, Optional

from app.repositories.feedback_learning import SemanticUpdateCandidateRepository
from app.schemas.feedback_learning import NormalizedCandidate


class CandidateWriterService:
    def __init__(self, *, candidate_repository: Optional[SemanticUpdateCandidateRepository] = None) -> None:
        self._candidate_repository = candidate_repository or SemanticUpdateCandidateRepository()

    def upsert_candidate(self, candidate: NormalizedCandidate) -> Dict[str, Any]:
        existing = self._candidate_repository.find_by_payload_scope(
            payload_hash=candidate.payload_hash,
            source_scope=candidate.source_scope,
            workspace_scope_key=candidate.workspace_scope_key,
        )
        if existing is None:
            result = self._candidate_repository.insert_candidate(payload=candidate.model_dump(mode="json"))
            candidate_id = int(result.lastrowid or 0)
            inserted = self._candidate_repository.get_by_id(candidate_id=candidate_id) if candidate_id > 0 else None
            if inserted is not None:
                return inserted
            fallback = candidate.model_dump(mode="json")
            fallback["id"] = candidate_id
            return fallback

        evidence_count = int(existing.get("evidence_count") or 0) + 1
        confidence = _blend_confidence(existing_confidence=existing.get("confidence"), proposed_confidence=candidate.confidence)
        self._candidate_repository.update_evidence_and_confidence(
            candidate_id=int(existing["id"]),
            evidence_count=evidence_count,
            confidence=confidence,
        )
        updated = dict(existing)
        updated["evidence_count"] = evidence_count
        updated["confidence"] = confidence
        return updated


def _blend_confidence(*, existing_confidence: Any, proposed_confidence: float) -> float:
    existing = float(existing_confidence or 0.0)
    proposed = float(proposed_confidence or 0.0)
    high = max(existing, proposed)
    low = min(existing, proposed)
    return (high * 0.7) + (low * 0.3)


__all__ = ["CandidateWriterService"]
