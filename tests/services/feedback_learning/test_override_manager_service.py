from __future__ import annotations

from app.adapters.query_port import ForgeExecResult
from app.exceptions.forge_error import ForgeError
from app.schemas.feedback_learning import NormalizedCandidate
from app.services.feedback_learning.override_manager_service import OverrideManagerService


class _SemanticOverrideRepository:
    def __init__(self, existing=None, inserted=None):
        self.existing = existing
        self.inserted = inserted or {"id": 21, "status": "active"}
        self.find_calls = []
        self.insert_calls = []
        self.get_calls = []

    def find_active_override(self, *, workspace_id, concept_key, override_type, override_key):
        self.find_calls.append(
            {
                "workspace_id": workspace_id,
                "concept_key": concept_key,
                "override_type": override_type,
                "override_key": override_key,
            }
        )
        return self.existing

    def insert_override(self, *, payload):
        self.insert_calls.append(payload)
        return ForgeExecResult(rowcount=1, lastrowid=21)

    def get_by_id(self, *, override_id: int):
        self.get_calls.append(override_id)
        return self.inserted


class _DomainOverrideRepository:
    def __init__(self, existing=None, inserted=None):
        self.existing = existing
        self.inserted = inserted or {"id": 31, "status": "active"}
        self.find_calls = []
        self.insert_calls = []
        self.get_calls = []

    def find_active_override(self, *, workspace_id, domain_key, override_type, override_key):
        self.find_calls.append(
            {
                "workspace_id": workspace_id,
                "domain_key": domain_key,
                "override_type": override_type,
                "override_key": override_key,
            }
        )
        return self.existing

    def insert_override(self, *, payload):
        self.insert_calls.append(payload)
        return ForgeExecResult(rowcount=1, lastrowid=31)

    def get_by_id(self, *, override_id: int):
        self.get_calls.append(override_id)
        return self.inserted


class _CandidateRepository:
    def __init__(self):
        self.calls = []

    def update_review(self, *, candidate_id: int, governance_status: str, reviewed_by=None, reviewed_at=None, auto_apply_eligible=None, governance_reason_code=None, review_notes=None):
        self.calls.append(
            {
                "candidate_id": candidate_id,
                "governance_status": governance_status,
                "reviewed_by": reviewed_by,
                "reviewed_at": reviewed_at,
                "auto_apply_eligible": auto_apply_eligible,
                "governance_reason_code": governance_reason_code,
                "review_notes": review_notes,
            }
        )
        return 1


def _candidate(*, target_type="semantic_override", concept_key="student_name", domain_key=None, change_type="add_alias", payload_json=None) -> NormalizedCandidate:
    return NormalizedCandidate.model_validate(
        {
            "id": 88,
            "failure_analysis_id": 55,
            "target_type": target_type,
            "concept_key": concept_key,
            "domain_key": domain_key,
            "change_type": change_type,
            "payload_json": payload_json or {"alias_key": "preferred_name", "match_kind": "exact", "aliases": ["Preferred Name"]},
            "payload_hash": "hash-55",
            "risk_level": "low",
            "evidence_count": 3,
            "confidence": 0.95,
            "governance_status": "pending",
            "auto_apply_eligible": True,
            "source_scope": "workspace",
            "workspace_id": "ws-1",
            "workspace_scope_key": "workspace:ws-1",
        }
    )


def test_override_manager_service_applies_semantic_override_with_review_metadata() -> None:
    candidate_repository = _CandidateRepository()
    semantic_override_repository = _SemanticOverrideRepository(inserted={"id": 21, "status": "active", "concept_key": "student_name"})
    service = OverrideManagerService(
        candidate_repository=candidate_repository,
        semantic_override_repository=semantic_override_repository,
        domain_override_repository=_DomainOverrideRepository(),
    )

    result = service.apply_candidate(_candidate(), approved_by="admin-1")

    assert result["candidate_status"] == "approved"
    assert semantic_override_repository.insert_calls[0]["override_key"] == "preferred_name"
    assert candidate_repository.calls[0]["governance_reason_code"] == "MANUAL_APPROVAL"


def test_override_manager_service_raises_for_unsupported_target_types() -> None:
    service = OverrideManagerService(
        candidate_repository=_CandidateRepository(),
        semantic_override_repository=_SemanticOverrideRepository(),
        domain_override_repository=_DomainOverrideRepository(),
    )

    try:
        service.apply_candidate(_candidate(target_type="manual_review", concept_key=None, payload_json={"note": "needs review"}), approved_by="admin-1")
        assert False, "expected unsupported target type failure"
    except ForgeError as exc:
        assert exc.status_code == 400


def test_override_manager_service_reuses_existing_identical_override() -> None:
    existing = {
        "id": 99,
        "workspace_id": "ws-1",
        "concept_key": "student_name",
        "override_value_json": {"alias_key": "preferred_name", "match_kind": "exact", "aliases": ["Preferred Name"]},
        "status": "active",
    }
    candidate_repository = _CandidateRepository()
    semantic_override_repository = _SemanticOverrideRepository(existing=existing)
    service = OverrideManagerService(
        candidate_repository=candidate_repository,
        semantic_override_repository=semantic_override_repository,
        domain_override_repository=_DomainOverrideRepository(),
    )

    result = service.apply_candidate(_candidate(), approved_by="admin-1")

    assert result["override"] == existing
    assert semantic_override_repository.insert_calls == []
