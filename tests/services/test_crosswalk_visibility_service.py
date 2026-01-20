from __future__ import annotations

from datetime import datetime, timezone

from app.services.crosswalks.crosswalk_visibility_service import CrosswalkVisibilityService
from tests._support.fakes import FakeSQLExecutor


def test_crosswalk_visibility_groups_and_flags_shared() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses = [
        [
            {
                "list_type": "regions",
                "list_id": "list-1",
                "list_name": "My Regions",
                "owner": "alice",
                "user_id": "user-1",
                "is_shared": 1,
                "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "updated_at": datetime(2024, 1, 2, tzinfo=timezone.utc),
            },
            {
                "list_type": "npiCategories",
                "list_id": "list-2",
                "list_name": "My NPIs",
                "owner": "bob",
                "user_id": "user-2",
                "is_shared": 0,
                "created_at": datetime(2024, 2, 1, tzinfo=timezone.utc),
                "updated_at": datetime(2024, 2, 2, tzinfo=timezone.utc),
            },
        ]
    ]

    svc = CrosswalkVisibilityService(workspace_id="ws-1", user_id="user-1", sql=fake)
    result = svc.get_index()

    assert result.has_shared is True
    assert len(result.index.regions) == 1
    assert len(result.index.npiCategories) == 1
    assert len(result.index.serviceLines) == 0

    regions = result.index.regions[0]
    assert regions.list_name == "My Regions"
    assert regions.user_id == "user-1"
    assert regions.is_shared is True
    assert regions.list_id == "list-1"
    assert regions.row_count == 0
    assert regions.expires_at is None

    query = fake.query_mappings_calls[0].query
    assert "crosswalk_list_meta" in query
    params = fake.query_mappings_calls[0].params or {}
    assert params["ws"] == "ws-1"
    assert params["uid"] == "user-1"
