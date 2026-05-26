from __future__ import annotations

from app.adapters.query_port import ForgeExecResult
from app.repositories.feedback_learning import DomainOverrideRepository, SemanticOverrideRepository
from tests._support.fakes import FakeForgeQueryPort


def test_semantic_override_repository_serializes_override_payload() -> None:
    sql = FakeForgeQueryPort()
    sql.insert_responses.append(ForgeExecResult(rowcount=1, lastrowid=11))

    repo = SemanticOverrideRepository(sql=sql)
    result = repo.insert_override(
        payload={
            "workspace_id": "ws-1",
            "concept_key": "student_name",
            "override_type": "alias_hint",
            "override_key": "preferred_name",
            "override_value": {"aliases": ["preferred name"]},
            "source_candidate_id": 5,
            "status": "active",
            "approved_by": "admin-1",
        }
    )

    assert result.lastrowid == 11
    assert sql.insert_calls[0].params["override_value_json"] == '{"aliases":["preferred name"]}'


def test_domain_override_repository_parses_value_json() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses.append(
        [
            {
                "id": 14,
                "workspace_id": None,
                "domain_key": "attendance",
                "override_type": "example_prompt",
                "override_key": "days_off",
                "override_value_json": '{"prompt":"Show me days off"}',
                "source_candidate_id": 8,
                "status": "active",
                "approved_by": "admin-1",
                "created_at": "2026-04-23 10:00:00",
                "updated_at": "2026-04-23 10:01:00",
            }
        ]
    )

    repo = DomainOverrideRepository(sql=sql)
    row = repo.get_by_id(override_id=14)

    assert row is not None
    assert row["override_value_json"] == {"prompt": "Show me days off"}


def test_domain_override_repository_uses_global_workspace_lookup_when_none() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses.append([])

    repo = DomainOverrideRepository(sql=sql)
    row = repo.find_active_override(
        workspace_id=None,
        domain_key="attendance",
        override_type="example_prompt",
        override_key="days_off",
    )

    assert row is None
    assert "workspace_id IS NULL" in sql.query_mappings_calls[0].query
    assert sql.query_mappings_calls[0].params == {
        "domain_key": "attendance",
        "override_type": "example_prompt",
        "override_key": "days_off",
    }

