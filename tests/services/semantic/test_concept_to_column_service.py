from __future__ import annotations

from app.services.semantic.concept_to_column_service import ConceptToColumnService
from tests._support.fakes import FakeSQLExecutor


def test_concept_mapping_query_returns_columns() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [
            {
                "model_column_id": 100,
                "table_name": "dim_student",
                "column_name": "grade_level",
                "concept_key": "GRADE_LEVEL",
                "weight": 1.0,
            }
        ],
        [
            {
                "model_column_id": 101,
                "table_name": "dim_student",
                "column_name": "race_ethnicity",
                "concept_key": "RACE",
                "weight": 0.8,
            }
        ],
    ]
    svc = ConceptToColumnService(sql=sql)

    out = svc.map_concepts_to_columns(
        workspace_id="ws-1",
        vertical_norm="education",
        concept_hits=[{"concept_key": "GRADE_LEVEL"}, {"concept_key": "RACE"}],
        max_columns=20,
    )

    assert out["concepts"] == ["GRADE_LEVEL", "RACE"]
    assert len(out["mapped_columns"]) == 2
    assert set(out["candidate_model_column_ids"]) == {100, 101}
