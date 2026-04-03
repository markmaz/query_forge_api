from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.user.workspace_user_query import (
    build_workspace_user_list_query,
    validate_workspace_user_list_args,
)


def test_validate_workspace_user_list_args_enforces_bounds() -> None:
    with pytest.raises(ForgeError):
        validate_workspace_user_list_args(workspace_id="", limit=1, offset=0)
    with pytest.raises(ForgeError):
        validate_workspace_user_list_args(workspace_id="ws", limit="bad", offset=0)
    with pytest.raises(ForgeError):
        validate_workspace_user_list_args(workspace_id="ws", limit=0, offset=0)
    with pytest.raises(ForgeError):
        validate_workspace_user_list_args(workspace_id="ws", limit=1, offset=-1)


def test_build_workspace_user_list_query_populates_search_params() -> None:
    query, params = build_workspace_user_list_query(
        workspace_id="ws1",
        q="Alice",
        limit=25,
        offset=10,
        include_inactive=False,
    )

    assert "workspace_membership" in query
    assert params["ws"] == "ws1"
    assert params["include_inactive"] == 0
    assert params["q_is_null"] == 0
    assert params["q_like"] == "%alice%"
