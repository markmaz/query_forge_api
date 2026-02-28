from __future__ import annotations

from app.services.semantic.concept_to_column_service import ConceptToColumnService
from tests._support.fakes import FakeSQLExecutor


def test_concept_mapping_query_returns_columns() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [
            {
                "model_column_id": 100,
                "workspace_table_id": 10,
                "table_name": "dim_student",
                "column_name": "grade_level",
                "model_table_name": "dim_student",
                "concept_key": "GRADE_LEVEL",
                "weight": 1.0,
                "base_weight": 1.0,
                "entity_bonus": 2.0,
                "dim_bonus": 1.0,
                "fact_penalty": 0.0,
                "alias_bonus": 0.5,
                "final_score": 4.5,
                "source": "m2m",
            }
        ],
        [
            {
                "model_column_id": 101,
                "workspace_table_id": 10,
                "table_name": "dim_student",
                "column_name": "race_ethnicity",
                "model_table_name": "dim_student",
                "concept_key": "RACE",
                "weight": 0.8,
                "base_weight": 1.0,
                "entity_bonus": 0.0,
                "dim_bonus": 1.0,
                "fact_penalty": 0.0,
                "alias_bonus": 0.0,
                "final_score": 2.0,
                "source": "fallback_primary",
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
    assert out["mapped_columns"][0]["concept_key"] == "GRADE_LEVEL"
    assert out["mapped_columns"][0]["source"] == "m2m"
    assert out["mapped_columns"][0]["final_score"] == 4.5
    assert out["mapped_columns"][1]["source"] == "fallback_primary"
    assert out["ranked_candidates_by_concept"]["GRADE_LEVEL"][0]["model_column_id"] == 100
    assert out["ranked_candidates_by_concept"]["RACE"][0]["model_column_id"] == 101

    assert len(sql.query_mappings_calls) == 2
    m2m_query = sql.query_mappings_calls[0].query
    fallback_query = sql.query_mappings_calls[1].query
    assert "FROM model_column_semantic_concept_map m" in m2m_query
    assert "ROW_NUMBER() OVER" in m2m_query
    assert "rn <= :per_concept_limit" in m2m_query
    assert "COLLATE utf8mb4_0900_ai_ci" in m2m_query
    assert "COLLATE utf8mb4_unicode_ci" in m2m_query
    assert "mc.semantic_concept_key IN" in fallback_query
    assert "COLLATE utf8mb4_0900_ai_ci" in fallback_query
    assert "COLLATE utf8mb4_unicode_ci" in fallback_query


def test_concept_mapping_rejects_race_ethnicity_to_city_with_warning() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [
            {
                "model_column_id": 901,
                "workspace_table_id": 10,
                "table_name": "dim_student",
                "column_name": "race_ethnicity",
                "model_table_name": "dim_student",
                "concept_key": "CITY",
                "authoritative_concept_key": "RACE",
                "authoritative_match": 0,
                "weight": 1.0,
                "base_weight": 1.0,
                "entity_bonus": 0.0,
                "dim_bonus": 1.0,
                "fact_penalty": 0.0,
                "alias_bonus": 0.0,
                "authoritative_bonus": -0.75,
                "final_score": 1.25,
                "source": "m2m",
            },
            {
                "model_column_id": 901,
                "workspace_table_id": 10,
                "table_name": "dim_student",
                "column_name": "race_ethnicity",
                "model_table_name": "dim_student",
                "concept_key": "RACE",
                "authoritative_concept_key": "RACE",
                "authoritative_match": 1,
                "weight": 1.0,
                "base_weight": 1.0,
                "entity_bonus": 0.0,
                "dim_bonus": 1.0,
                "fact_penalty": 0.0,
                "alias_bonus": 0.0,
                "authoritative_bonus": 0.75,
                "final_score": 2.75,
                "source": "m2m",
            },
        ]
    ]
    svc = ConceptToColumnService(sql=sql)

    out = svc.map_concepts_to_columns(
        workspace_id="ws-1",
        vertical_norm="education",
        concept_hits=[{"concept_key": "CITY"}, {"concept_key": "RACE"}],
        max_columns=20,
    )

    assert all(str(row.get("concept_key") or "").upper() != "CITY" for row in out["mapped_columns"])
    assert any("rejected_mapping_conflict concept=CITY" in str(w) for w in out["warnings"])


def test_concept_mapping_entity_intent_ranks_student_name_over_staff_name() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [
            {
                "model_column_id": 201,
                "workspace_table_id": 11,
                "table_name": "dim_staff",
                "column_name": "last_name",
                "model_table_name": "dim_staff",
                "concept_key": "LAST_NAME",
                "entity": "student",
                "semantic_type": "identifier",
                "weight": 1.0,
                "base_weight": 1.0,
                "entity_bonus": 0.0,
                "dim_bonus": 1.0,
                "fact_penalty": 0.0,
                "alias_bonus": 0.0,
                "authoritative_bonus": 0.0,
                "authoritative_match": 0,
                "final_score": 2.0,
                "source": "m2m",
            },
            {
                "model_column_id": 202,
                "workspace_table_id": 12,
                "table_name": "dim_student",
                "column_name": "last_name",
                "model_table_name": "dim_student",
                "concept_key": "LAST_NAME",
                "entity": "student",
                "semantic_type": "identifier",
                "weight": 1.0,
                "base_weight": 1.0,
                "entity_bonus": 2.0,
                "dim_bonus": 1.0,
                "fact_penalty": 0.0,
                "alias_bonus": 0.0,
                "authoritative_bonus": 0.0,
                "authoritative_match": 0,
                "final_score": 4.0,
                "source": "m2m",
            },
        ]
    ]
    svc = ConceptToColumnService(sql=sql)

    out = svc.map_concepts_to_columns(
        workspace_id="ws-1",
        vertical_norm="education",
        concept_hits=[{"concept_key": "LAST_NAME"}],
        max_columns=20,
        intent_entity="student",
    )

    assert out["mapped_columns"][0]["model_column_id"] == 202
    assert out["mapped_columns"][0]["effective_weight"] > out["mapped_columns"][1]["effective_weight"]


def test_concept_mapping_student_name_intent_boosts_student_specific_and_downranks_generic_staff() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses = [
        [
            {
                "model_column_id": 301,
                "workspace_table_id": 21,
                "table_name": "dim_student",
                "column_name": "first_name",
                "model_table_name": "dim_student",
                "concept_key": "STUDENT_FIRST_NAME",
                "entity": "student",
                "semantic_type": "attribute",
                "weight": 1.0,
                "base_weight": 1.0,
                "entity_bonus": 1.0,
                "dim_bonus": 1.0,
                "fact_penalty": 0.0,
                "alias_bonus": 0.0,
                "authoritative_bonus": 0.0,
                "authoritative_match": 0,
                "final_score": 3.0,
                "source": "m2m",
            },
            {
                "model_column_id": 302,
                "workspace_table_id": 21,
                "table_name": "dim_student",
                "column_name": "first_name",
                "model_table_name": "dim_student",
                "concept_key": "FIRST_NAME",
                "entity": None,
                "semantic_type": "attribute",
                "weight": 1.0,
                "base_weight": 1.0,
                "entity_bonus": 0.0,
                "dim_bonus": 1.0,
                "fact_penalty": 0.0,
                "alias_bonus": 0.0,
                "authoritative_bonus": 0.0,
                "authoritative_match": 0,
                "final_score": 2.0,
                "source": "m2m",
            },
            {
                "model_column_id": 303,
                "workspace_table_id": 22,
                "table_name": "dim_staff",
                "column_name": "first_name",
                "model_table_name": "dim_staff",
                "concept_key": "STAFF_FIRST_NAME",
                "entity": "staff",
                "semantic_type": "attribute",
                "weight": 1.0,
                "base_weight": 1.0,
                "entity_bonus": 0.0,
                "dim_bonus": 1.0,
                "fact_penalty": 0.0,
                "alias_bonus": 0.0,
                "authoritative_bonus": 0.0,
                "authoritative_match": 0,
                "final_score": 1.5,
                "source": "m2m",
            },
        ]
    ]
    svc = ConceptToColumnService(sql=sql)

    out = svc.map_concepts_to_columns(
        workspace_id="ws-1",
        vertical_norm="education",
        concept_hits=[
            {"concept_key": "STUDENT_FIRST_NAME"},
            {"concept_key": "FIRST_NAME"},
            {"concept_key": "STAFF_FIRST_NAME"},
        ],
        max_columns=20,
        intent_entity="student",
    )

    by_key = {row["concept_key"]: row for row in out["mapped_columns"]}
    assert by_key["STUDENT_FIRST_NAME"]["effective_weight"] > by_key["FIRST_NAME"]["effective_weight"]
    assert by_key["FIRST_NAME"]["effective_weight"] > by_key["STAFF_FIRST_NAME"]["effective_weight"]
