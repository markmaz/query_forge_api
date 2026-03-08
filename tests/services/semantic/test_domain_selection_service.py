from __future__ import annotations

from app.services.semantic.domain_selection_service import DomainSelectionService
from tests._support.fakes import FakeForgeQueryPort


def test_choose_domain_id_prefers_domain_with_required_concept_coverage() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {"domain_id": 1, "table_name": "dim_student"},
            {"domain_id": 1, "table_name": "fct_student_school_association"},
            {"domain_id": 2, "table_name": "dim_school"},
        ]
    ]
    svc = DomainSelectionService(sql=sql)

    out = svc.choose_domain_id(
        workspace_id="ws-1",
        mapped_columns=[
            {"concept_key": "BIRTH_COUNTRY", "table_name": "dim_student", "model_column_id": 2050, "final_score": 4.0},
            {"concept_key": "STUDENT_ID", "table_name": "fct_student_school_association", "model_column_id": 1115, "final_score": 2.0},
        ],
        required_concept_keys=["BIRTH_COUNTRY", "STUDENT_ID"],
        prompt="show all kids",
        preselected_domain_id=None,
    )

    assert out["domain_id"] == 1
    assert out["threshold_met"] is True
    assert any(row["domain_id"] == 1 and row["coverage"] >= 1.0 for row in out["domains"])
