from __future__ import annotations

import pytest

from app.adapters.query_port import ForgeExecResult
from app.schemas.feedback_learning import NormalizedCandidate
from app.services.feedback_learning.candidate_writer_service import CandidateWriterService


class _CandidateRepository:
    def __init__(self, *, existing=None, inserted=None):
        self.existing = existing
        self.inserted = inserted
        self.find_calls = []
        self.insert_calls = []
        self.get_calls = []
        self.update_calls = []

    def find_by_payload_scope(self, *, payload_hash: str, source_scope: str, workspace_scope_key: str):
        self.find_calls.append(
            {
                "payload_hash": payload_hash,
                "source_scope": source_scope,
                "workspace_scope_key": workspace_scope_key,
            }
        )
        return self.existing

    def insert_candidate(self, *, payload):
        self.insert_calls.append(payload)
        return ForgeExecResult(rowcount=1, lastrowid=101)

    def get_by_id(self, *, candidate_id: int):
        self.get_calls.append(candidate_id)
        if self.inserted is not None:
            return self.inserted
        return None

    def update_evidence_and_confidence(self, *, candidate_id: int, evidence_count: int, confidence: float):
        self.update_calls.append(
            {
                "candidate_id": candidate_id,
                "evidence_count": evidence_count,
                "confidence": confidence,
            }
        )
        return 1


def _candidate() -> NormalizedCandidate:
    return NormalizedCandidate.model_validate(
        {
            "failure_analysis_id": 15,
            "target_type": "semantic_override",
            "concept_key": "student_name",
            "domain_key": None,
            "change_type": "add_alias",
            "payload_json": {"alias_key": "preferred_name", "match_kind": "exact", "aliases": ["Preferred Name"]},
            "payload_hash": "hash-15",
            "risk_level": "low",
            "evidence_count": 1,
            "confidence": 0.9,
            "governance_status": "pending",
            "auto_apply_eligible": False,
            "source_scope": "workspace",
            "workspace_id": "ws-1",
            "workspace_scope_key": "workspace:ws-1",
        }
    )


def test_candidate_writer_service_inserts_new_candidate() -> None:
    repository = _CandidateRepository(
        inserted={
            "id": 101,
            "payload_hash": "hash-15",
            "evidence_count": 1,
            "confidence": 0.9,
        }
    )
    service = CandidateWriterService(candidate_repository=repository)

    row = service.upsert_candidate(_candidate())

    assert row["id"] == 101
    assert repository.insert_calls[0]["payload_hash"] == "hash-15"
    assert repository.insert_calls[0]["payload_json"] == {"alias_key": "preferred_name", "match_kind": "exact", "aliases": ["Preferred Name"]}


def test_candidate_writer_service_dedupes_and_blends_confidence() -> None:
    repository = _CandidateRepository(
        existing={
            "id": 88,
            "payload_hash": "hash-15",
            "evidence_count": 2,
            "confidence": 0.4,
        }
    )
    service = CandidateWriterService(candidate_repository=repository)

    row = service.upsert_candidate(_candidate())

    assert row["id"] == 88
    assert repository.update_calls == [
        {
            "candidate_id": 88,
            "evidence_count": 3,
            "confidence": pytest.approx(0.75),
        }
    ]
    assert row["evidence_count"] == 3
    assert row["confidence"] == pytest.approx(0.75)
