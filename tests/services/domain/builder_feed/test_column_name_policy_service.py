from __future__ import annotations

from app.services.domain.builder_feed.column_name_policy_service import ColumnNamePolicyService
from tests._support.fakes import FakeForgeQueryPort


def test_column_name_policy_service_defaults_when_domain_missing() -> None:
    service = ColumnNamePolicyService(sql=FakeForgeQueryPort())
    assert service.get_policy(workspace_id="ws", domain_id=None) == "DEDUP_PRIMARY_FIRST"


def test_column_name_policy_service_reads_supported_policy() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[{"column_name_policy": "SHOW_ALL_QUALIFIED"}]]
    service = ColumnNamePolicyService(sql=sql)
    assert service.get_policy(workspace_id="ws", domain_id=1) == "SHOW_ALL_QUALIFIED"
