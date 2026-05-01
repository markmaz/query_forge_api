from __future__ import annotations

from app.adapters.query_port import ForgeExecResult
from app.repositories.feedback_learning import CatalogPromotionAuditRepository
from tests._support.fakes import FakeForgeQueryPort


def test_create_audit_inserts_payload() -> None:
    sql = FakeForgeQueryPort()
    sql.insert_responses.append(ForgeExecResult(rowcount=1, lastrowid=23))

    repo = CatalogPromotionAuditRepository(sql=sql)
    result = repo.create_audit(
        payload={
            "source_type": "candidate",
            "source_id": 5,
            "target_table": "semantic_concept_alias",
            "target_record_key": "student_name:preferred_name",
            "promotion_action": "insert",
            "promotion_status": "succeeded",
            "promoted_by": "admin-1",
            "promoted_at": "2026-04-23 12:00:00",
            "retry_count": 0,
            "last_retry_at": None,
            "notes": "approved from feedback",
            "error_message": None,
        }
    )

    assert result.lastrowid == 23
    assert sql.insert_calls[0].params["target_table"] == "semantic_concept_alias"


def test_list_audits_returns_rows_and_total() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses.append(
        [
            {
                "id": 23,
                "source_type": "candidate",
                "source_id": 5,
                "target_table": "semantic_concept_alias",
                "target_record_key": "student_name:preferred_name",
                "promotion_action": "insert",
                "promotion_status": "succeeded",
                "promoted_by": "admin-1",
                "promoted_at": "2026-04-23 12:00:00",
                "retry_count": 0,
                "last_retry_at": None,
                "notes": "approved from feedback",
                "error_message": None,
                "created_at": "2026-04-23 12:00:00",
            }
        ]
    )
    sql.query_mappings_responses.append([{"total": 1}])

    repo = CatalogPromotionAuditRepository(sql=sql)
    page = repo.list_audits(source_type="candidate", promotion_status="succeeded", limit=10, offset=20)

    assert page["total"] == 1
    assert page["limit"] == 10
    assert page["offset"] == 20
    assert page["rows"][0]["id"] == 23


def test_update_failure_writes_retry_state() -> None:
    sql = FakeForgeQueryPort()
    sql.write_responses.append(1)

    repo = CatalogPromotionAuditRepository(sql=sql)
    updated = repo.update_failure(
        audit_id=23,
        retry_count=2,
        last_retry_at="2026-04-23 13:00:00",
        error_message="write failed",
    )

    assert updated == 1
    assert sql.write_calls[0].params == {
        "id": 23,
        "retry_count": 2,
        "last_retry_at": "2026-04-23 13:00:00",
        "error_message": "write failed",
        "promotion_status": "failed",
    }


def test_get_latest_by_source_returns_latest_matching_row() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses.append(
        [
            {
                "id": 44,
                "source_type": "semantic_override",
                "source_id": 11,
                "target_table": "semantic_concept_alias",
                "target_record_key": "student_name:preferred_name",
                "promotion_action": "upsert_alias",
                "promotion_status": "failed",
                "promoted_by": "admin-1",
                "promoted_at": "2026-04-23 12:00:00",
                "retry_count": 1,
                "last_retry_at": "2026-04-23 12:05:00",
                "notes": None,
                "error_message": "write failed",
                "created_at": "2026-04-23 12:00:00",
            }
        ]
    )

    repo = CatalogPromotionAuditRepository(sql=sql)
    row = repo.get_latest_by_source(
        source_type="semantic_override",
        source_id=11,
        promotion_action="upsert_alias",
        target_table="semantic_concept_alias",
    )

    assert row is not None
    assert row["id"] == 44
    assert sql.query_mappings_calls[0].params == {
        "source_type": "semantic_override",
        "source_id": 11,
        "promotion_action": "upsert_alias",
        "target_table": "semantic_concept_alias",
    }
