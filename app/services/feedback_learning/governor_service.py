from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from app.config.feedback_learning_config import (
    FEEDBACK_AUTO_APPLY_ENABLED,
    FEEDBACK_CONFIDENCE_THRESHOLD,
    FEEDBACK_DOMAIN_EXAMPLE_CONFIDENCE_THRESHOLD,
    FEEDBACK_EVIDENCE_THRESHOLD,
)
from app.constants.feedback_learning import AUTO_APPLY_CHANGE_TYPES, BLOCKED_CHANGE_TYPES, NON_OVERRIDE_TARGET_TYPES
from app.repositories.feedback_learning import DomainOverrideRepository, SemanticOverrideRepository
from app.schemas.feedback_learning import GovernanceDecision, NormalizedCandidate


class GovernorService:
    def __init__(
        self,
        *,
        semantic_override_repository: Optional[SemanticOverrideRepository] = None,
        domain_override_repository: Optional[DomainOverrideRepository] = None,
    ) -> None:
        self._semantic_override_repository = semantic_override_repository or SemanticOverrideRepository()
        self._domain_override_repository = domain_override_repository or DomainOverrideRepository()

    def evaluate_candidate(self, candidate: NormalizedCandidate) -> GovernanceDecision:
        if candidate.target_type in {member.value for member in NON_OVERRIDE_TARGET_TYPES}:
            return _decision("needs_review", False, "NON_OVERRIDE_TARGET_TYPE")

        if candidate.change_type in BLOCKED_CHANGE_TYPES:
            return _decision("needs_review", False, "BLOCKED_CHANGE_TYPE")

        if not _payload_is_well_formed(candidate):
            return _decision("rejected", False, "MALFORMED_PAYLOAD")

        if self._is_no_op(candidate):
            return _decision("rejected", False, "NO_OP_DETECTED")

        if not FEEDBACK_AUTO_APPLY_ENABLED:
            return _decision("needs_review", False, "AUTO_APPLY_DISABLED")

        if candidate.change_type not in AUTO_APPLY_CHANGE_TYPES:
            return _decision("needs_review", False, "CHANGE_TYPE_NOT_ALLOWED")

        if candidate.risk_level != "low":
            return _decision("needs_review", False, "RISK_NOT_LOW")

        confidence_threshold = _confidence_threshold_for(candidate)
        if float(candidate.confidence) < confidence_threshold:
            return _decision("needs_review", False, "CONFIDENCE_BELOW_THRESHOLD")

        if int(candidate.evidence_count) < int(FEEDBACK_EVIDENCE_THRESHOLD):
            return _decision("needs_review", False, "EVIDENCE_BELOW_THRESHOLD")

        if self._has_conflict(candidate):
            return _decision("needs_review", False, "CONFLICT_DETECTED")

        return _decision("pending", True, "AUTO_APPLY_ELIGIBLE")

    def _is_no_op(self, candidate: NormalizedCandidate) -> bool:
        for row in self._matching_active_overrides(candidate):
            if row.get("override_value_json") == candidate.payload_json:
                return True
        return False

    def _has_conflict(self, candidate: NormalizedCandidate) -> bool:
        if candidate.change_type in {"concept_rank_boost", "concept_rank_penalty", "add_phrase_hint", "add_ambiguity_note", "add_domain_example_prompt", "add_domain_lexical_hint"}:
            return False
        if candidate.change_type == "add_alias":
            alias_key = _optional_text(candidate.payload_json.get("alias_key") or candidate.payload_json.get("alias"))
            match_kind = _optional_text(candidate.payload_json.get("match_kind")) or "exact"
            if alias_key is None:
                return False
            for row in self._semantic_override_repository.list_overrides(workspace_id=candidate.workspace_id, status="active"):
                if _optional_text(row.get("override_type")) != "add_alias":
                    continue
                if _optional_text(row.get("override_key")) != alias_key:
                    continue
                value_json = row.get("override_value_json") if isinstance(row.get("override_value_json"), dict) else {}
                row_match_kind = _optional_text(value_json.get("match_kind")) or "exact"
                if row_match_kind != match_kind:
                    continue
                if _optional_text(row.get("concept_key")) != candidate.concept_key:
                    return True
        return False

    def _matching_active_overrides(self, candidate: NormalizedCandidate) -> Iterable[Dict[str, Any]]:
        if candidate.target_type == "semantic_override":
            for row in self._semantic_override_repository.list_overrides(
                workspace_id=candidate.workspace_id,
                status="active",
                concept_key=candidate.concept_key,
            ):
                if _optional_text(row.get("override_type")) == candidate.change_type and _optional_text(row.get("override_key")) == _override_key(candidate):
                    yield row
            return

        if candidate.target_type == "domain_override":
            for row in self._domain_override_repository.list_overrides(
                workspace_id=candidate.workspace_id,
                status="active",
                domain_key=candidate.domain_key,
            ):
                if _optional_text(row.get("override_type")) == candidate.change_type and _optional_text(row.get("override_key")) == _override_key(candidate):
                    yield row


def _confidence_threshold_for(candidate: NormalizedCandidate) -> float:
    if candidate.change_type == "add_domain_example_prompt":
        return float(FEEDBACK_DOMAIN_EXAMPLE_CONFIDENCE_THRESHOLD)
    return float(FEEDBACK_CONFIDENCE_THRESHOLD)


def _payload_is_well_formed(candidate: NormalizedCandidate) -> bool:
    payload = candidate.payload_json
    if candidate.change_type == "add_alias":
        return bool(_optional_text(payload.get("alias_key") or payload.get("alias")))
    if candidate.change_type in {"add_phrase_hint", "add_domain_lexical_hint"}:
        return bool(_optional_text(payload.get("phrase") or payload.get("hint") or payload.get("phrase_hint")))
    if candidate.change_type == "add_domain_example_prompt":
        return bool(_optional_text(payload.get("prompt")))
    if candidate.change_type == "add_ambiguity_note":
        return bool(_optional_text(payload.get("note") or payload.get("ambiguity_note")))
    if candidate.change_type in {"concept_rank_boost", "concept_rank_penalty"}:
        value = payload.get("weight", payload.get("score_delta"))
        return isinstance(value, (int, float))
    return bool(payload)


def _override_key(candidate: NormalizedCandidate) -> str:
    payload = candidate.payload_json
    if candidate.change_type == "add_alias":
        return _optional_text(payload.get("alias_key") or payload.get("alias")) or candidate.change_type
    if candidate.change_type == "add_domain_example_prompt":
        return _optional_text(payload.get("example_key") or payload.get("prompt_key") or payload.get("prompt")) or candidate.change_type
    return _optional_text(payload.get("override_key") or payload.get("hint") or payload.get("phrase") or payload.get("note")) or candidate.change_type


def _decision(governance_status: str, auto_apply_eligible: bool, reason_code: str) -> GovernanceDecision:
    return GovernanceDecision.model_validate(
        {
            "governance_status": governance_status,
            "auto_apply_eligible": auto_apply_eligible,
            "reason_code": reason_code,
        }
    )


def _optional_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


__all__ = ["GovernorService"]
