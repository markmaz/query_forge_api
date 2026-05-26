from __future__ import annotations

from app.schemas.feedback_learning import ProposedChange
from app.services.feedback_learning.candidate_normalizer import CandidateNormalizer


def _change(*, target_type: str = "semantic_override", target_key: str = "student_name", change_type: str = "add_alias", payload=None, risk_level: str = "low", confidence: float = 0.91) -> ProposedChange:
    return ProposedChange.model_validate(
        {
            "target_type": target_type,
            "target_key": target_key,
            "change_type": change_type,
            "payload": payload or {"alias_key": "Preferred Name", "match_kind": "exact"},
            "risk_level": risk_level,
            "confidence": confidence,
        }
    )


def test_candidate_normalizer_produces_same_hash_for_equivalent_payloads() -> None:
    normalizer = CandidateNormalizer()

    first = normalizer.normalize(
        failure_analysis_id=11,
        workspace_id="ws-1",
        proposed_change=_change(payload={"match_kind": "exact", "alias_key": "Preferred Name"}),
    )
    second = normalizer.normalize(
        failure_analysis_id=11,
        workspace_id="ws-1",
        proposed_change=_change(payload={"alias_key": "Preferred Name", "match_kind": "exact"}),
    )

    assert first.payload_hash == second.payload_hash
    assert first.workspace_scope_key == "workspace:ws-1"
    assert first.concept_key == "student_name"


def test_candidate_normalizer_scope_changes_affect_hash() -> None:
    normalizer = CandidateNormalizer()

    workspace_candidate = normalizer.normalize(
        failure_analysis_id=12,
        workspace_id="ws-1",
        proposed_change=_change(),
    )
    global_candidate = normalizer.normalize(
        failure_analysis_id=12,
        workspace_id="ws-1",
        proposed_change=_change(payload={"alias_key": "Preferred Name", "match_kind": "exact", "source_scope": "global"}),
    )

    assert workspace_candidate.payload_hash != global_candidate.payload_hash
    assert workspace_candidate.source_scope == "workspace"
    assert global_candidate.source_scope == "global"
    assert global_candidate.workspace_id is None
    assert global_candidate.workspace_scope_key == "global"


def test_candidate_normalizer_workspace_changes_affect_hash() -> None:
    normalizer = CandidateNormalizer()

    first = normalizer.normalize(
        failure_analysis_id=13,
        workspace_id="ws-1",
        proposed_change=_change(target_type="domain_override", target_key="attendance", change_type="add_domain_example_prompt", payload={"prompt": "Show me attendance exceptions"}),
    )
    second = normalizer.normalize(
        failure_analysis_id=13,
        workspace_id="ws-2",
        proposed_change=_change(target_type="domain_override", target_key="attendance", change_type="add_domain_example_prompt", payload={"prompt": "Show me attendance exceptions"}),
    )

    assert first.payload_hash != second.payload_hash
    assert first.domain_key == "attendance"
    assert second.workspace_scope_key == "workspace:ws-2"
