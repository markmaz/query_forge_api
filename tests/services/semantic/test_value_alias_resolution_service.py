from __future__ import annotations

from app.services.semantic.value_alias_resolution_service import ValueAliasResolutionService
from tests._support.fakes import FakeForgeQueryPort


def test_value_alias_resolution_maps_metro_schools_to_district_name() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "concept_key": "DISTRICT_NAME",
                "semantic_concept_id": 12,
                "canonical_value": "Davidson County",
                "alias_value": "metro schools",
                "match_kind": "exact",
                "weight": 1.0,
            }
        ],
        [],
        [],
    ]
    svc = ValueAliasResolutionService(sql=sql)

    out = svc.resolve(prompt="metro schools")

    assert out == [
        {
            "concept_key": "DISTRICT_NAME",
            "semantic_concept_id": 12,
            "canonical_value": "Davidson County",
            "matched_alias": "metro schools",
            "matched_ngram": "metro schools",
            "match_kind": "exact",
            "weight": 1.0,
        }
    ]
    assert len(sql.query_mappings_calls) == 3
    assert "FROM semantic_value_alias va" in sql.query_mappings_calls[0].query
    assert "vertical_norm" not in (sql.query_mappings_calls[0].params or {})
