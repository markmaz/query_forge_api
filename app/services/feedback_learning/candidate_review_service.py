from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from app.exceptions.forge_error import ForgeError
from app.repositories.feedback_learning import (
    CatalogPromotionAuditRepository,
    DomainOverrideRepository,
    PromptFailureAnalysisRepository,
    PromptFeedbackRepository,
    SemanticOverrideRepository,
    SemanticUpdateCandidateRepository,
)
from app.schemas.feedback_learning import NormalizedCandidate
from app.services.feedback_learning.override_manager_service import OverrideManagerService


class CandidateReviewService:
    def __init__(
        self,
        *,
        candidate_repository: Optional[SemanticUpdateCandidateRepository] = None,
        analysis_repository: Optional[PromptFailureAnalysisRepository] = None,
        prompt_feedback_repository: Optional[PromptFeedbackRepository] = None,
        semantic_override_repository: Optional[SemanticOverrideRepository] = None,
        domain_override_repository: Optional[DomainOverrideRepository] = None,
        promotion_audit_repository: Optional[CatalogPromotionAuditRepository] = None,
        override_manager_service: Optional[OverrideManagerService] = None,
    ) -> None:
        self._candidate_repository = candidate_repository or SemanticUpdateCandidateRepository()
        self._analysis_repository = analysis_repository or PromptFailureAnalysisRepository()
        self._prompt_feedback_repository = prompt_feedback_repository or PromptFeedbackRepository()
        self._semantic_override_repository = semantic_override_repository or SemanticOverrideRepository()
        self._domain_override_repository = domain_override_repository or DomainOverrideRepository()
        self._promotion_audit_repository = promotion_audit_repository or CatalogPromotionAuditRepository()
        self._override_manager_service = override_manager_service or OverrideManagerService(
            candidate_repository=self._candidate_repository,
            semantic_override_repository=self._semantic_override_repository,
            domain_override_repository=self._domain_override_repository,
        )

    def list_candidates(self, **filters) -> Dict[str, Any]:
        page = self._candidate_repository.list_candidates(**filters)
        rows = [self._enrich_candidate_row(dict(row)) for row in page.get("rows") or []]
        return {
            "rows": rows,
            "total": page.get("total", 0),
            "page": page.get("page", 1),
            "page_size": page.get("page_size", 50),
        }

    def get_candidate_detail(self, *, candidate_id: int) -> Dict[str, Any]:
        candidate = self._candidate_repository.get_by_id(candidate_id=int(candidate_id))
        if candidate is None:
            raise ForgeError("Feedback learning candidate not found", status_code=404)
        enriched = self._enrich_candidate_row(dict(candidate))
        return {
            "candidate": _candidate_summary(enriched),
            "analysis_summary": enriched.get("analysis_summary"),
            "source_feedback": enriched.get("source_feedback"),
            "effective_target_key": enriched.get("effective_target_key"),
        }

    def approve_candidate(self, *, candidate_id: int, reviewed_by: str) -> Dict[str, Any]:
        candidate = self._get_candidate_or_404(candidate_id)
        result = self._override_manager_service.apply_candidate(candidate, approved_by=reviewed_by)
        result["candidate"] = _candidate_summary(self._enrich_candidate_row(result.get("candidate") or candidate.model_dump(mode="json")))
        return result

    def reject_candidate(self, *, candidate_id: int, reviewed_by: str, reason: str) -> Dict[str, Any]:
        candidate = self._get_candidate_or_404(candidate_id)
        reason_text = str(reason or "").strip()
        if reason_text == "":
            raise ForgeError("rejection reason is required", status_code=400)
        raw_id = getattr(candidate, "id", None)
        if raw_id in (None, ""):
            raise ForgeError("candidate id is required", status_code=500)
        self._candidate_repository.update_review(
            candidate_id=int(raw_id),
            governance_status="rejected",
            reviewed_by=str(reviewed_by or "").strip() or None,
            reviewed_at=datetime.now(timezone.utc),
            auto_apply_eligible=False,
            governance_reason_code="MANUAL_REJECTION",
            review_notes=reason_text,
        )
        row = candidate.model_dump(mode="json")
        row["id"] = int(raw_id)
        row["governance_status"] = "rejected"
        row["governance_reason_code"] = "MANUAL_REJECTION"
        row["review_notes"] = reason_text
        return {"candidate": _candidate_summary(self._enrich_candidate_row(row))}

    def bulk_approve(self, *, candidate_ids: Iterable[int], reviewed_by: str) -> Dict[str, Any]:
        results = [self.approve_candidate(candidate_id=int(candidate_id), reviewed_by=reviewed_by) for candidate_id in candidate_ids]
        return {"processed": len(results), "results": results}

    def bulk_reject(self, *, candidate_ids: Iterable[int], reviewed_by: str, reason: str) -> Dict[str, Any]:
        results = [self.reject_candidate(candidate_id=int(candidate_id), reviewed_by=reviewed_by, reason=reason) for candidate_id in candidate_ids]
        return {"processed": len(results), "results": results}

    def list_semantic_overrides(self, *, workspace_id: str) -> list[Dict[str, Any]]:
        return self._semantic_override_repository.list_overrides(workspace_id=workspace_id, status="active")

    def list_domain_overrides(self, *, workspace_id: str) -> list[Dict[str, Any]]:
        return self._domain_override_repository.list_overrides(workspace_id=workspace_id, status="active")

    def deactivate_semantic_override(self, *, override_id: int, reviewed_by: str) -> Dict[str, Any]:
        row = self._semantic_override_repository.get_by_id(override_id=int(override_id))
        if row is None:
            raise ForgeError("Semantic override not found", status_code=404)
        self._semantic_override_repository.deactivate(override_id=int(override_id))
        out = dict(row)
        out["status"] = "inactive"
        out["deactivated_by"] = str(reviewed_by or "").strip() or None
        return out

    def deactivate_domain_override(self, *, override_id: int, reviewed_by: str) -> Dict[str, Any]:
        row = self._domain_override_repository.get_by_id(override_id=int(override_id))
        if row is None:
            raise ForgeError("Domain override not found", status_code=404)
        self._domain_override_repository.deactivate(override_id=int(override_id))
        out = dict(row)
        out["status"] = "inactive"
        out["deactivated_by"] = str(reviewed_by or "").strip() or None
        return out

    def list_promotion_audits(self, **filters) -> Dict[str, Any]:
        return self._promotion_audit_repository.list_audits(**filters)

    def _get_candidate_or_404(self, candidate_id: int) -> NormalizedCandidate:
        row = self._candidate_repository.get_by_id(candidate_id=int(candidate_id))
        if row is None:
            raise ForgeError("Feedback learning candidate not found", status_code=404)
        return _to_candidate_model(row)

    def _enrich_candidate_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        analysis = self._analysis_repository.get_by_id(analysis_id=int(row.get("failure_analysis_id") or 0))
        source_feedback = None
        if analysis is not None:
            prompt_feedback_id = int(analysis.get("prompt_feedback_id") or 0)
            source_feedback = self._prompt_feedback_repository.get_feedback(prompt_feedback_id=prompt_feedback_id) if prompt_feedback_id > 0 else None
        row["analysis_summary"] = _analysis_summary(analysis)
        row["source_feedback"] = _feedback_summary(source_feedback)
        row["effective_target_key"] = row.get("concept_key") or row.get("domain_key")
        return row


def _to_candidate_model(row: Dict[str, Any]) -> NormalizedCandidate:
    payload = dict(row)
    payload["payload_json"] = dict(payload.get("payload_json") or {})
    return NormalizedCandidate.model_validate(payload)


def _analysis_summary(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {
        "analysis_id": row.get("id"),
        "prompt_feedback_id": row.get("prompt_feedback_id"),
        "status": row.get("status"),
        "failure_verdict": row.get("failure_verdict"),
        "confidence": row.get("confidence"),
        "analysis_json": row.get("analysis_json"),
    }


def _feedback_summary(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {
        "prompt_feedback_id": row.get("id"),
        "workspace_id": row.get("workspace_id"),
        "user_id": row.get("user_id"),
        "vote": row.get("vote"),
        "normalized_prompt": row.get("normalized_prompt"),
        "prompt_text": row.get("prompt_text"),
    }


def _candidate_summary(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "failure_analysis_id": row.get("failure_analysis_id"),
        "target_type": row.get("target_type"),
        "concept_key": row.get("concept_key"),
        "domain_key": row.get("domain_key"),
        "change_type": row.get("change_type"),
        "payload_json": row.get("payload_json"),
        "payload_hash": row.get("payload_hash"),
        "risk_level": row.get("risk_level"),
        "evidence_count": row.get("evidence_count"),
        "confidence": row.get("confidence"),
        "governance_status": row.get("governance_status"),
        "auto_apply_eligible": row.get("auto_apply_eligible"),
        "governance_reason_code": row.get("governance_reason_code"),
        "review_notes": row.get("review_notes"),
        "workspace_id": row.get("workspace_id"),
        "source_scope": row.get("source_scope"),
        "workspace_scope_key": row.get("workspace_scope_key"),
    }


__all__ = ["CandidateReviewService"]
