from __future__ import annotations

from app.services.feedback_learning.runtime_override_resolver import RuntimeOverrideResolver


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


class _DomainOverrideRepository:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def list_overrides(self, *, workspace_id=None, status=None, domain_key=None):
        out = list(self.rows)
        if workspace_id is None:
            out = [row for row in out if row.get("workspace_id") is None]
        else:
            out = [row for row in out if row.get("workspace_id") == workspace_id]
        if status is not None:
            out = [row for row in out if row.get("status") == status]
        if domain_key is not None:
            out = [row for row in out if row.get("domain_key") == domain_key]
        return out


def test_runtime_override_resolver_merges_alias_rows_without_mutating_base_rows() -> None:
    resolver = RuntimeOverrideResolver(
        semantic_override_repository=_SemanticOverrideRepository(
            [
                {
                    "workspace_id": None,
                    "concept_key": "STUDENT_NAME",
                    "override_type": "add_alias",
                    "override_key": "preferred_name",
                    "override_value_json": {
                        "alias_key": "preferred_name",
                        "match_kind": "exact",
                        "weight": 0.8,
                    },
                    "status": "active",
                }
            ]
        ),
        domain_override_repository=_DomainOverrideRepository(),
    )
    base_rows = [
        {
            "concept_key": "STUDENT_NAME",
            "alias_key": "student name",
            "weight": 1.0,
            "match_kind": "contains",
        }
    ]

    out = resolver.resolve_alias_rows(base_rows=base_rows, workspace_id="ws-1")

    assert base_rows == [
        {
            "concept_key": "STUDENT_NAME",
            "alias_key": "student name",
            "weight": 1.0,
            "match_kind": "contains",
        }
    ]
    assert out == [
        {
            "concept_key": "STUDENT_NAME",
            "alias_key": "student name",
            "weight": 1.0,
            "match_kind": "contains",
        },
        {
            "concept_key": "STUDENT_NAME",
            "alias_key": "preferred_name",
            "weight": 0.8,
            "match_kind": "exact",
            "source": "feedback_override",
        },
    ]


def test_runtime_override_resolver_prefers_workspace_override_for_same_alias_key() -> None:
    resolver = RuntimeOverrideResolver(
        semantic_override_repository=_SemanticOverrideRepository(
            [
                {
                    "workspace_id": None,
                    "concept_key": "STUDENT_NAME",
                    "override_type": "add_alias",
                    "override_key": "preferred_name",
                    "override_value_json": {
                        "alias_key": "preferred_name",
                        "match_kind": "exact",
                        "weight": 0.4,
                    },
                    "status": "active",
                },
                {
                    "workspace_id": "ws-1",
                    "concept_key": "STUDENT_NAME",
                    "override_type": "add_alias",
                    "override_key": "preferred_name",
                    "override_value_json": {
                        "alias_key": "preferred_name",
                        "match_kind": "exact",
                        "weight": 0.9,
                    },
                    "status": "active",
                },
            ]
        ),
        domain_override_repository=_DomainOverrideRepository(),
    )

    out = resolver.resolve_alias_rows(base_rows=[], workspace_id="ws-1")

    assert out == [
        {
            "concept_key": "STUDENT_NAME",
            "alias_key": "preferred_name",
            "weight": 0.9,
            "match_kind": "exact",
            "source": "feedback_override",
        }
    ]


def test_runtime_override_resolver_accumulates_score_adjustments_and_domain_hints() -> None:
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
                },
                {
                    "workspace_id": "ws-1",
                    "concept_key": "ENROLLMENT_COUNT",
                    "override_type": "concept_rank_penalty",
                    "override_key": "penalty-a",
                    "override_value_json": {"delta": 0.10},
                    "status": "active",
                },
                {
                    "workspace_id": "ws-1",
                    "concept_key": "ENROLLMENT_COUNT",
                    "override_type": "concept_rank_boost",
                    "override_key": "ignored-inactive",
                    "override_value_json": {"delta": 1.0},
                    "status": "inactive",
                },
            ]
        ),
        domain_override_repository=_DomainOverrideRepository(
            [
                {
                    "workspace_id": None,
                    "domain_key": "ENROLLMENT",
                    "override_type": "add_domain_example_prompt",
                    "override_key": "prompt-a",
                    "override_value_json": {"prompt": "show me students by campus"},
                    "status": "active",
                },
                {
                    "workspace_id": "ws-1",
                    "domain_key": "ENROLLMENT",
                    "override_type": "add_domain_lexical_hint",
                    "override_key": "lexical-a",
                    "override_value_json": {"hint": "headcount"},
                    "status": "active",
                },
                {
                    "workspace_id": "ws-1",
                    "domain_key": "ENROLLMENT",
                    "override_type": "add_ambiguity_note",
                    "override_key": "note-a",
                    "override_value_json": {"note": "clarify whether to use active enrollment"},
                    "status": "active",
                },
            ]
        ),
    )
    base_rows = [
        {
            "id": 7,
            "concept_key": "ENROLLMENT_COUNT",
            "name": "Enrollment Count",
            "description": "",
            "semantic_type": "metric",
        }
    ]

    concept_rows = resolver.resolve_concept_rows(base_rows=base_rows, workspace_id="ws-1")
    domain_hints = resolver.resolve_domain_hints(domain_key="ENROLLMENT", workspace_id="ws-1")

    assert concept_rows[0]["feedback_score_adjustment"] == 0.15
    assert domain_hints == {
        "example_prompts": ["show me students by campus"],
        "lexical_hints": ["headcount"],
        "ambiguity_notes": ["clarify whether to use active enrollment"],
    }
