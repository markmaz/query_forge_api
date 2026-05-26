from __future__ import annotations

from app.schemas.feedback_learning import NormalizedCandidate
from app.services.feedback_learning.governor_service import GovernorService


class _SemanticOverrideRepository:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def list_overrides(self, *, workspace_id=None, status=None, concept_key=None):
        out = list(self.rows)
        if workspace_id is not None:
            out = [row for row in out if row.get("workspace_id") == workspace_id]
        if status is not None:
            out = [row for row in out if row.get("status") == status]
        if concept_key is not None:
            out = [row for row in out if row.get("concept_key") == concept_key]
        return out


class _DomainOverrideRepository:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def list_overrides(self, *, workspace_id=None, status=None, domain_key=None):
        out = list(self.rows)
        if workspace_id is not None:
            out = [row for row in out if row.get("workspace_id") == workspace_id]
        if status is not None:
            out = [row for row in out if row.get("status") == status]
        if domain_key is not None:
            out = [row for row in out if row.get("domain_key") == domain_key]
        return out


def _candidate(
    *,
    target_type: str = "semantic_override",
    change_type: str = "add_alias",
    payload_json=None,
    confidence: float = 0.91,
    evidence_count: int = 3,
    risk_level: str = "low",
    concept_key: str | None = "student_name",
    domain_key: str | None = None,
) -> NormalizedCandidate:
    return NormalizedCandidate.model_validate(
        {
            "failure_analysis_id": 9,
            "target_type": target_type,
            "concept_key": concept_key,
            "domain_key": domain_key,
            "change_type": change_type,
            "payload_json": payload_json or {"alias_key": "preferred_name", "match_kind": "exact", "aliases": ["Preferred Name"]},
            "payload_hash": "hash-1",
            "risk_level": risk_level,
            "evidence_count": evidence_count,
            "confidence": confidence,
            "governance_status": "pending",
            "auto_apply_eligible": False,
            "source_scope": "workspace",
            "workspace_id": "ws-1",
            "workspace_scope_key": "workspace:ws-1",
        }
    )


def test_governor_service_marks_manual_review_targets_for_review() -> None:
    service = GovernorService(
        semantic_override_repository=_SemanticOverrideRepository(),
        domain_override_repository=_DomainOverrideRepository(),
    )

    decision = service.evaluate_candidate(_candidate(target_type="manual_review", change_type="review_packet", payload_json={"note": "needs human review"}, concept_key=None))

    assert decision.governance_status == "needs_review"
    assert decision.reason_code == "NON_OVERRIDE_TARGET_TYPE"
    assert decision.auto_apply_eligible is False


def test_governor_service_marks_blocked_change_types_for_review() -> None:
    service = GovernorService(
        semantic_override_repository=_SemanticOverrideRepository(),
        domain_override_repository=_DomainOverrideRepository(),
    )

    decision = service.evaluate_candidate(_candidate(change_type="new_concept", payload_json={"concept_key": "new_student_concept"}))

    assert decision.governance_status == "needs_review"
    assert decision.reason_code == "BLOCKED_CHANGE_TYPE"


def test_governor_service_rejects_malformed_payloads() -> None:
    service = GovernorService(
        semantic_override_repository=_SemanticOverrideRepository(),
        domain_override_repository=_DomainOverrideRepository(),
    )

    decision = service.evaluate_candidate(_candidate(payload_json={"match_kind": "exact"}))

    assert decision.governance_status == "rejected"
    assert decision.reason_code == "MALFORMED_PAYLOAD"


def test_governor_service_rejects_no_op_override() -> None:
    service = GovernorService(
        semantic_override_repository=_SemanticOverrideRepository(
            [
                {
                    "id": 5,
                    "workspace_id": "ws-1",
                    "concept_key": "student_name",
                    "override_type": "add_alias",
                    "override_key": "preferred_name",
                    "override_value_json": {"alias_key": "preferred_name", "match_kind": "exact", "aliases": ["Preferred Name"]},
                    "status": "active",
                }
            ]
        ),
        domain_override_repository=_DomainOverrideRepository(),
    )

    decision = service.evaluate_candidate(_candidate())

    assert decision.governance_status == "rejected"
    assert decision.reason_code == "NO_OP_DETECTED"


def test_governor_service_uses_stricter_domain_example_prompt_threshold() -> None:
    service = GovernorService(
        semantic_override_repository=_SemanticOverrideRepository(),
        domain_override_repository=_DomainOverrideRepository(),
    )

    decision = service.evaluate_candidate(
        _candidate(
            target_type="domain_override",
            change_type="add_domain_example_prompt",
            payload_json={"prompt": "Show me attendance exceptions"},
            confidence=0.89,
            concept_key=None,
            domain_key="attendance",
        )
    )

    assert decision.governance_status == "needs_review"
    assert decision.reason_code == "CONFIDENCE_BELOW_THRESHOLD"


def test_governor_service_marks_full_pass_candidates_auto_apply_eligible() -> None:
    service = GovernorService(
        semantic_override_repository=_SemanticOverrideRepository(),
        domain_override_repository=_DomainOverrideRepository(),
    )

    decision = service.evaluate_candidate(_candidate())

    assert decision.governance_status == "pending"
    assert decision.reason_code == "AUTO_APPLY_ELIGIBLE"
    assert decision.auto_apply_eligible is True
