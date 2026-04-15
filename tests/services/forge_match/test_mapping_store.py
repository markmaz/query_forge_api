from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.forge_match.mapping_store import ForgeMatchMappingStore
from tests._support.fakes import FakeForgeQueryPort


def _store(sql: FakeForgeQueryPort) -> ForgeMatchMappingStore:
    return ForgeMatchMappingStore(
        sql=sql,
        session_reader=type(
            "_Reader",
            (),
            {
                "get_session_row": lambda self, **kwargs: {"id": kwargs["session_id"]},
            },
        )(),
        allowed_result_statuses={"accepted", "rejected", "needs_review", "manually_mapped", "suggested"},
    )


def test_patch_mappings_wraps_expected_manual_column_parse_errors() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"id": "map-1", "session_id": "sess-1"}],
    ]
    store = _store(sql)
    store.assert_workspace_column = lambda **kwargs: None  # type: ignore[method-assign]

    with pytest.raises(ForgeError, match="manually_selected_workspace_column_id must be integer"):
        store.patch_mappings(
            workspace_id="ws-1",
            session_id="sess-1",
            reviewer_user_id="user-1",
            updates=[
                {
                    "mapping_id": "map-1",
                    "action": "remap",
                    "manually_selected_workspace_column_id": "bad",
                }
            ],
        )


def test_patch_mappings_surfaces_unexpected_manual_column_parse_errors() -> None:
    class _BadInt:
        def __int__(self) -> int:
            raise AssertionError("unexpected manual column parse bug")

    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"id": "map-1", "session_id": "sess-1"}],
    ]
    store = _store(sql)
    store.assert_workspace_column = lambda **kwargs: None  # type: ignore[method-assign]

    with pytest.raises(AssertionError, match="unexpected manual column parse bug"):
        store.patch_mappings(
            workspace_id="ws-1",
            session_id="sess-1",
            reviewer_user_id="user-1",
            updates=[
                {
                    "mapping_id": "map-1",
                    "action": "remap",
                    "manually_selected_workspace_column_id": _BadInt(),
                }
            ],
        )
