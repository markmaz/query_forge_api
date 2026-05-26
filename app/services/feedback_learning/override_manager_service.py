from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.exceptions.forge_error import ForgeError
from app.repositories.feedback_learning import DomainOverrideRepository, SemanticOverrideRepository, SemanticUpdateCandidateRepository
from app.schemas.feedback_learning import NormalizedCandidate
from app.services.feedback_learning.common import derive_override_key


class OverrideManagerService:
    def __init__(
        self,
        *,
        candidate_repository: Optional[SemanticUpdateCandidateRepository] = None,
        semantic_override_repository: Optional[SemanticOverrideRepository] = None,
        domain_override_repository: Optional[DomainOverrideRepository] = None,
    ) -> None:
        self._candidate_repository = candidate_repository or SemanticUpdateCandidateRepository()
        self._semantic_override_repository = semantic_override_repository or SemanticOverrideRepository()
        self._domain_override_repository = domain_override_repository or DomainOverrideRepository()

    def apply_candidate(self, candidate: NormalizedCandidate, approved_by: Optional[str] = None) -> Dict[str, Any]:
        reviewed_by = str(approved_by or "").strip() or None
        candidate_row = candidate.model_dump(mode="json")
        if candidate.target_type == "semantic_override":
            override = self._apply_semantic_override(candidate, approved_by=reviewed_by)
        elif candidate.target_type == "domain_override":
            override = self._apply_domain_override(candidate, approved_by=reviewed_by)
        else:
            raise ForgeError("Unsupported candidate target type for override application", status_code=400)

        candidate_id = _candidate_id(candidate)
        if candidate_id is not None:
            self._candidate_repository.update_review(
                candidate_id=candidate_id,
                governance_status="approved",
                reviewed_by=reviewed_by,
                reviewed_at=datetime.now(timezone.utc),
                auto_apply_eligible=False,
                governance_reason_code="MANUAL_APPROVAL",
                review_notes=None,
            )
            candidate_row["governance_status"] = "approved"
            candidate_row["governance_reason_code"] = "MANUAL_APPROVAL"

        return {
            "candidate": candidate_row,
            "candidate_status": "approved",
            "override": override,
        }

    def _apply_semantic_override(self, candidate: NormalizedCandidate, *, approved_by: Optional[str]) -> Dict[str, Any]:
        override_key = derive_override_key(change_type=candidate.change_type, payload_json=candidate.payload_json)
        existing = self._semantic_override_repository.find_active_override(
            workspace_id=candidate.workspace_id,
            concept_key=str(candidate.concept_key or ""),
            override_type=candidate.change_type,
            override_key=override_key,
        )
        if existing is not None and existing.get("override_value_json") == candidate.payload_json:
            return existing
        if existing is not None:
            raise ForgeError("Active semantic override already exists for this key", status_code=409)
        result = self._semantic_override_repository.insert_override(
            payload={
                "workspace_id": candidate.workspace_id,
                "concept_key": candidate.concept_key,
                "override_type": candidate.change_type,
                "override_key": override_key,
                "override_value_json": candidate.payload_json,
                "source_candidate_id": _candidate_id(candidate),
                "status": "active",
                "approved_by": approved_by,
            }
        )
        override_id = int(result.lastrowid or 0)
        return self._semantic_override_repository.get_by_id(override_id=override_id) or {"id": override_id}

    def _apply_domain_override(self, candidate: NormalizedCandidate, *, approved_by: Optional[str]) -> Dict[str, Any]:
        override_key = derive_override_key(change_type=candidate.change_type, payload_json=candidate.payload_json)
        existing = self._domain_override_repository.find_active_override(
            workspace_id=candidate.workspace_id,
            domain_key=str(candidate.domain_key or ""),
            override_type=candidate.change_type,
            override_key=override_key,
        )
        if existing is not None and existing.get("override_value_json") == candidate.payload_json:
            return existing
        if existing is not None:
            raise ForgeError("Active domain override already exists for this key", status_code=409)
        result = self._domain_override_repository.insert_override(
            payload={
                "workspace_id": candidate.workspace_id,
                "domain_key": candidate.domain_key,
                "override_type": candidate.change_type,
                "override_key": override_key,
                "override_value_json": candidate.payload_json,
                "source_candidate_id": _candidate_id(candidate),
                "status": "active",
                "approved_by": approved_by,
            }
        )
        override_id = int(result.lastrowid or 0)
        return self._domain_override_repository.get_by_id(override_id=override_id) or {"id": override_id}


def _candidate_id(candidate: NormalizedCandidate) -> Optional[int]:
    raw = getattr(candidate, "id", None)
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


__all__ = ["OverrideManagerService"]
