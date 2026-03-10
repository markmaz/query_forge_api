from __future__ import annotations

from datetime import datetime

from app.services.domain.builder_column_feed_service import (
    BuilderColumnFeedService,
    BuilderFeedQuery,
    _qf_json_safe,
    _qf_snake_to_camel,
)
from tests._support.fakes import FakeForgeQueryPort


def test_snake_to_camel() -> None:
    assert _qf_snake_to_camel("workspace_table_id") == "workspaceTableId"


def test_json_safe() -> None:
    assert _qf_json_safe(datetime(2024, 1, 1)) == "2024-01-01T00:00:00"


def test_list_available_columns_default_policy() -> None:
    sql = FakeForgeQueryPort()
    sql.query_responses = [[(1,)]]
    sql.query_mappings_responses = [
        [
            {
                "workspace_table_id": 1,
                "full_name": "main.asset.tbl",
                "column_name": "id",
                "data_type": "STRING",
                "is_primary": 1,
                "sort_order": 0,
                "ordinal_position": 1,
            }
        ]
    ]
    service = BuilderColumnFeedService(sql=sql)
    res = service.list_available_columns(
        BuilderFeedQuery(workspace_id="ws1", user_id="u1", limit=1, offset=0)
    )
    assert res["total"] == 1
    assert res["rows"][0]["columnName"] == "id"


def test_list_available_columns_show_all() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"column_name_policy": "SHOW_ALL_QUALIFIED"}],
        [
            {
                "workspace_table_id": 1,
                "full_name": "main.asset.tbl",
                "column_name": "id",
                "data_type": "STRING",
                "is_primary": 1,
                "sort_order": 0,
                "ordinal_position": 1,
            }
        ],
    ]
    sql.query_responses = [[(1,)]]
    service = BuilderColumnFeedService(sql=sql)
    res = service.list_available_columns(
        BuilderFeedQuery(workspace_id="ws1", user_id="u1", domain_id=1, limit=1, offset=0)
    )
    assert res["columnNamePolicy"] == "SHOW_ALL_QUALIFIED"
