from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List

from app.services.semantic.semantic_assignment_service import SemanticAssignmentService
from tests._support.fakes import FakeForgeQueryPort


@dataclass
class _SyncCall:
    model_column_id: int
    updates: Dict[str, Any]


class _GatewayStub:
    def __init__(self) -> None:
        self.calls: List[_SyncCall] = []

    def sync_column_patch_from_model(self, *, model_column_id: int, updates: Dict[str, Any]) -> int:
        self.calls.append(_SyncCall(model_column_id=model_column_id, updates=dict(updates)))
        return 1


def test_upsert_primary_semantics_mirrors_to_workspace_when_row_updated() -> None:
    sql = FakeForgeQueryPort()
    sql.write_responses = [1]
    gw = _GatewayStub()
    svc = SemanticAssignmentService(sql=sql, metadata_gateway=gw)  # type: ignore[arg-type]

    affected = svc.upsert_primary_semantics(
        model_column_id=44,
        semantic_concept_id=9,
        key="STUDENT_ID",
        source="llm",
        confidence=0.91,
        reasons=["identifier-like values"],
        warnings=[],
        entity="student",
        sub_type="id",
        granularity_rank=0,
    )

    assert affected == 1
    assert gw.calls
    call = gw.calls[0]
    assert call.model_column_id == 44
    assert call.updates["semantic_concept_id"] == 9
    assert call.updates["semantic_concept_key"] == "STUDENT_ID"
    assert call.updates["semantic_reasons_json"] == json.dumps(["identifier-like values"])

