from __future__ import annotations

from app.services.feedback_learning.runtime_override_resolver import RuntimeOverrideResolver
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


class _SemanticOverrideRepository:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def list_overrides(self, *, workspace_id=None, status=None, concept_key=None):
        out = list(self.rows)
        if workspace_id is None:
            out = [row for row in out if row.get("workspace_id") is None]
        else:
            out = [row for row in out if row.get("workspace_id") == workspace_id]
        if status is not None:
            out = [row for row in out if row.get("status") == status]
        if concept_key is not None:
            out = [row for row in out if row.get("concept_key") == concept_key]
        return out


def test_value_alias_resolution_includes_feedback_phrase_hints() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[], [], []]
    resolver = RuntimeOverrideResolver(
        semantic_override_repository=_SemanticOverrideRepository(
            [
                {
                    "workspace_id": "ws-1",
                    "concept_key": "DISTRICT_NAME",
                    "override_type": "add_phrase_hint",
                    "override_key": "metro schools",
                    "override_value_json": {"value": "metro schools"},
                    "status": "active",
                }
            ]
        )
    )
    svc = ValueAliasResolutionService(sql=sql, runtime_override_resolver=resolver)

    out = svc.resolve(prompt="metro schools", workspace_id="ws-1")

    assert out == [
        {
            "concept_key": "DISTRICT_NAME",
            "semantic_concept_id": None,
            "canonical_value": "metro schools",
            "matched_alias": "metro schools",
            "matched_ngram": "metro schools",
            "match_kind": "contains",
            "weight": 0.75,
        }
    ]
