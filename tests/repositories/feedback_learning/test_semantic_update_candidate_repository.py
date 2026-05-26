from __future__ import annotations

from app.adapters.query_port import ForgeExecResult
from app.repositories.feedback_learning import SemanticUpdateCandidateRepository
from tests._support.fakes import FakeForgeQueryPort


def test_insert_candidate_serializes_payload_json() -> None:
    sql = FakeForgeQueryPort()
    sql.insert_responses.append(ForgeExecResult(rowcount=1, lastrowid=101))

    repo = SemanticUpdateCandidateRepository(sql=sql)
    result = repo.insert_candidate(
        payload={
            "failure_analysis_id": 9,
            "target_type": "semantic_override",
            "concept_key": "student_name",
            "domain_key": None,
            "change_type": "add_alias",
            "payload_json": {"alias": "legal name"},
            "payload_hash": "abc123",
            "risk_level": "low",
            "evidence_count": 2,
            "confidence": 0.89,
            "governance_status": "pending",
            "auto_apply_eligible": True,
            "source_scope": "workspace",
            "workspace_id": "ws-1",
            "workspace_scope_key": "workspace:ws-1",
            "reviewed_by": None,
            "reviewed_at": None,
        }
    )

    assert result.lastrowid == 101
    assert sql.insert_calls[0].params["payload_json"] == '{"alias":"legal name"}'


def test_list_candidates_returns_normalized_rows_and_total() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses.append(
        [
            {
                "id": 5,
                "failure_analysis_id": 9,
                "target_type": "semantic_override",
                "concept_key": "student_name",
                "domain_key": None,
                "change_type": "add_alias",
                "payload_json": '{"alias":"preferred name"}',
                "payload_hash": "hash-1",
                "risk_level": "low",
                "evidence_count": 3,
                "confidence": 0.93,
                "governance_status": "pending",
                "auto_apply_eligible": 1,
                "source_scope": "workspace",
                "workspace_id": "ws-1",
                "workspace_scope_key": "workspace:ws-1",
                "reviewed_by": None,
                "reviewed_at": None,
                "created_at": "2026-04-23 10:00:00",
                "updated_at": "2026-04-23 10:01:00",
            }
        ]
    )
    sql.query_mappings_responses.append([{"total": 1}])

    repo = SemanticUpdateCandidateRepository(sql=sql)
    page = repo.list_candidates(
        governance_status="pending",
        workspace_id="ws-1",
        page=2,
        page_size=25,
    )

    assert page["total"] == 1
    assert page["page"] == 2
    assert page["page_size"] == 25
    assert page["rows"][0]["payload_json"] == {"alias": "preferred name"}
    assert sql.query_mappings_calls[0].params["offset"] == 25


def test_update_review_passes_review_fields() -> None:
    sql = FakeForgeQueryPort()
    sql.write_responses.append(1)

    repo = SemanticUpdateCandidateRepository(sql=sql)
    updated = repo.update_review(
        candidate_id=5,
        governance_status="approved",
        reviewed_by="admin-1",
        reviewed_at="2026-04-23 12:00:00",
        auto_apply_eligible=False,
        governance_reason_code="MANUAL_APPROVAL",
        review_notes="Reviewed and approved by admin",
    )

    assert updated == 1
    assert sql.write_calls[0].params == {
        "id": 5,
        "governance_status": "approved",
        "reviewed_by": "admin-1",
        "reviewed_at": "2026-04-23 12:00:00",
        "auto_apply_eligible": False,
        "governance_reason_code": "MANUAL_APPROVAL",
        "review_notes": "Reviewed and approved by admin",
    }
