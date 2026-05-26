from __future__ import annotations

from app.exceptions.forge_error import ForgeError
from app.services.feedback_learning.catalog_promotion_service import CatalogPromotionService
from tests._support.fakes import FakeForgeQueryPort


class _SemanticOverrideRepository:
    def __init__(self, row):
        self.row = row
        self.deactivate_calls = []

    def get_by_id(self, *, override_id: int):
        assert override_id == int(self.row["id"])
        return dict(self.row)

    def deactivate(self, *, override_id: int) -> int:
        self.deactivate_calls.append(override_id)
        return 1


class _DomainOverrideRepository:
    def __init__(self, row):
        self.row = row
        self.deactivate_calls = []

    def get_by_id(self, *, override_id: int):
        assert override_id == int(self.row["id"])
        return dict(self.row)

    def deactivate(self, *, override_id: int) -> int:
        self.deactivate_calls.append(override_id)
        return 1


class _AuditRepository:
    def __init__(self, latest_failed=None):
        self.latest_failed = latest_failed
        self.create_calls = []
        self.update_calls = []

    def create_audit(self, *, payload):
        self.create_calls.append(dict(payload))

        class _Result:
            lastrowid = 91

        return _Result()

    def update_failure(self, *, audit_id: int, retry_count: int, last_retry_at, error_message, promotion_status: str = "failed"):
        self.update_calls.append(
            {
                "audit_id": audit_id,
                "retry_count": retry_count,
                "last_retry_at": last_retry_at,
                "error_message": error_message,
                "promotion_status": promotion_status,
            }
        )
        return 1

    def get_latest_by_source(self, *, source_type: str, source_id: int, promotion_action=None, target_table=None):
        del source_type, source_id, promotion_action, target_table
        return self.latest_failed


def test_promote_semantic_alias_writes_alias_audit_and_deactivates_override() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses.append([])
    override_repo = _SemanticOverrideRepository(
        {
            "id": 11,
            "workspace_id": "ws-1",
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
    )
    audit_repo = _AuditRepository()
    service = CatalogPromotionService(
        sql=sql,
        semantic_override_repository=override_repo,
        domain_override_repository=_DomainOverrideRepository({"id": 0}),
        audit_repository=audit_repo,
    )

    result = service.promote_semantic_override(override_id=11, promoted_by="admin-1", notes="approved")

    assert result["promotion_status"] == "succeeded"
    assert sql.insert_calls[0].params == {
        "alias_key": "preferred_name",
        "concept_key": "STUDENT_NAME",
        "match_kind": "exact",
        "weight": 0.8,
    }
    assert audit_repo.create_calls[0]["target_table"] == "semantic_concept_alias"
    assert audit_repo.create_calls[0]["promotion_status"] == "succeeded"
    assert override_repo.deactivate_calls == [11]


def test_promote_semantic_rank_penalty_clamps_priority_at_zero() -> None:
    sql = FakeForgeQueryPort()
    sql.write_responses.append(1)
    override_repo = _SemanticOverrideRepository(
        {
            "id": 12,
            "workspace_id": "ws-1",
            "concept_key": "ENROLLMENT_COUNT",
            "override_type": "concept_rank_penalty",
            "override_key": "penalty-a",
            "override_value_json": {"delta": 3},
            "status": "active",
        }
    )
    audit_repo = _AuditRepository()
    service = CatalogPromotionService(
        sql=sql,
        semantic_override_repository=override_repo,
        domain_override_repository=_DomainOverrideRepository({"id": 0}),
        audit_repository=audit_repo,
    )

    result = service.promote_semantic_override(override_id=12, promoted_by="admin-1")

    assert result["promotion_status"] == "succeeded"
    assert "GREATEST(0, display_priority - :delta)" in sql.write_calls[0].query
    assert sql.write_calls[0].params == {
        "concept_key": "ENROLLMENT_COUNT",
        "delta": 3,
    }
    assert audit_repo.create_calls[0]["target_table"] == "semantic_concept"


def test_promote_domain_override_appends_tagged_note_to_domain_profile() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses.append([{"id": 6, "name": "Attendance"}])
    sql.query_mappings_responses.append([{"notes": "Existing note", "summary": None, "keywords": None, "entities": None, "metrics": None, "attributes": None, "synonyms": None, "acronyms": None}])
    sql.write_responses.append(1)
    override_repo = _DomainOverrideRepository(
        {
            "id": 21,
            "workspace_id": "ws-1",
            "domain_key": "ATTENDANCE",
            "override_type": "add_domain_example_prompt",
            "override_key": "days_off",
            "override_value_json": {"prompt": "Show me days off"},
            "status": "active",
        }
    )
    audit_repo = _AuditRepository()
    service = CatalogPromotionService(
        sql=sql,
        semantic_override_repository=_SemanticOverrideRepository({"id": 0}),
        domain_override_repository=override_repo,
        audit_repository=audit_repo,
    )

    result = service.promote_domain_override(override_id=21, promoted_by="admin-1", notes="ship it")

    assert result["promotion_status"] == "succeeded"
    assert "UPDATE domain_profile" in sql.write_calls[0].query
    assert "[feedback_learning:add_domain_example_prompt]" in sql.write_calls[0].params["notes"]
    assert "Show me days off" in sql.write_calls[0].params["notes"]
    assert override_repo.deactivate_calls == [21]
    assert audit_repo.create_calls[0]["target_table"] == "domain_profile"


def test_promote_domain_override_blocks_global_runtime_only_override_and_records_failure() -> None:
    sql = FakeForgeQueryPort()
    override_repo = _DomainOverrideRepository(
        {
            "id": 22,
            "workspace_id": None,
            "domain_key": "ATTENDANCE",
            "override_type": "add_domain_example_prompt",
            "override_key": "days_off",
            "override_value_json": {"prompt": "Show me days off"},
            "status": "active",
        }
    )
    audit_repo = _AuditRepository()
    service = CatalogPromotionService(
        sql=sql,
        semantic_override_repository=_SemanticOverrideRepository({"id": 0}),
        domain_override_repository=override_repo,
        audit_repository=audit_repo,
    )

    try:
        service.promote_domain_override(override_id=22, promoted_by="admin-1")
        assert False, "expected global runtime-only override failure"
    except ForgeError as exc:
        assert exc.status_code == 400

    assert audit_repo.create_calls[0]["promotion_status"] == "failed"
    assert override_repo.deactivate_calls == []


def test_promote_semantic_override_updates_existing_failed_audit_retry_metadata() -> None:
    sql = FakeForgeQueryPort()
    sql.write_exceptions.append(RuntimeError("db write failed"))
    override_repo = _SemanticOverrideRepository(
        {
            "id": 13,
            "workspace_id": "ws-1",
            "concept_key": "ENROLLMENT_COUNT",
            "override_type": "concept_rank_boost",
            "override_key": "boost-a",
            "override_value_json": {"delta": 2},
            "status": "active",
        }
    )
    audit_repo = _AuditRepository(
        latest_failed={
            "id": 71,
            "retry_count": 1,
            "promotion_status": "failed",
        }
    )
    service = CatalogPromotionService(
        sql=sql,
        semantic_override_repository=override_repo,
        domain_override_repository=_DomainOverrideRepository({"id": 0}),
        audit_repository=audit_repo,
    )

    try:
        service.promote_semantic_override(override_id=13, promoted_by="admin-1")
        assert False, "expected write failure"
    except RuntimeError as exc:
        assert str(exc) == "db write failed"

    assert audit_repo.create_calls == []
    assert audit_repo.update_calls[0]["audit_id"] == 71
    assert audit_repo.update_calls[0]["retry_count"] == 2

