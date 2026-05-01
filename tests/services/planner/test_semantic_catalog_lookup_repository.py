from __future__ import annotations

from app.services.feedback_learning.runtime_override_resolver import RuntimeOverrideResolver
from app.services.planner.semantic_catalog_lookup_repository import SemanticCatalogLookupRepository
from tests._support.fakes import FakeForgeQueryPort


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


def test_repository_load_aliases_merges_feedback_overrides() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "concept_key": "STUDENT_NAME",
                "alias_key": "student name",
                "weight": 1.0,
                "match_kind": "contains",
            }
        ]
    ]
    resolver = RuntimeOverrideResolver(
        semantic_override_repository=_SemanticOverrideRepository(
            [
                {
                    "workspace_id": "ws-1",
                    "concept_key": "STUDENT_NAME",
                    "override_type": "add_alias",
                    "override_key": "preferred_name",
                    "override_value_json": {
                        "alias_key": "preferred_name",
                        "match_kind": "exact",
                        "weight": 0.85,
                    },
                    "status": "active",
                }
            ]
        )
    )
    repo = SemanticCatalogLookupRepository(sql=sql, runtime_override_resolver=resolver)

    rows = repo.load_aliases(workspace_id="ws-1")

    assert rows[-1] == {
        "concept_key": "STUDENT_NAME",
        "alias_key": "preferred_name",
        "weight": 0.85,
        "match_kind": "exact",
        "source": "feedback_override",
    }


def test_repository_load_concepts_applies_feedback_score_adjustment() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": 9,
                "concept_key": "ENROLLMENT_COUNT",
                "name": "Enrollment Count",
                "description": "",
                "semantic_type": "metric",
                "status": "active",
            }
        ]
    ]
    resolver = RuntimeOverrideResolver(
        semantic_override_repository=_SemanticOverrideRepository(
            [
                {
                    "workspace_id": None,
                    "concept_key": "ENROLLMENT_COUNT",
                    "override_type": "concept_rank_boost",
                    "override_key": "boost-a",
                    "override_value_json": {"delta": 0.25},
                    "status": "active",
                }
            ]
        )
    )
    repo = SemanticCatalogLookupRepository(sql=sql, runtime_override_resolver=resolver)

    rows = repo.load_concepts(workspace_id="ws-1")

    assert rows[0]["feedback_score_adjustment"] == 0.25
