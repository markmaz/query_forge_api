from __future__ import annotations

import pytest

from app.exceptions.service_error import ServiceError
from app.services.workspace_user_read_service import WorkspaceUserReadService
from tests._support.fakes import FakeSQLExecutor


def test_list_workspace_users_validates_inputs() -> None:
    svc = WorkspaceUserReadService(sql=FakeSQLExecutor())
    with pytest.raises(ServiceError):
        svc.list_workspace_users(workspace_id="")
    with pytest.raises(ServiceError):
        svc.list_workspace_users(workspace_id="ws", limit="bad")
    with pytest.raises(ServiceError):
        svc.list_workspace_users(workspace_id="ws", limit=0)
    with pytest.raises(ServiceError):
        svc.list_workspace_users(workspace_id="ws", offset=-1)


def test_list_workspace_users_success() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_responses.append(
        [
            {
                "user_id": "u1",
                "username": "alice",
                "email": "a@example.com",
                "first_name": "Alice",
                "last_name": "Smith",
                "status": "Active",
                "is_default": 1,
                "display_name": "Alice Smith",
            }
        ]
    )
    svc = WorkspaceUserReadService(sql=fake)
    rows = svc.list_workspace_users(workspace_id="ws", include_inactive=False, q="ali")

    assert rows[0]["user_id"] == "u1"
    assert rows[0]["display_name"] == "Alice Smith"
