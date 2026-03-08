from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.value_overrides.list_read_service import ForgeListReadService
from tests._support.fakes import FakeForgeQueryPort


@dataclass
class _FakeTable:
    rows: list[dict]

    def to_pylist(self):
        return list(self.rows)


class _FakeDBX:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def submit_statement(self, sql, parameters=None, qf_result_fmt=None, **_kwargs):
        self.calls.append((sql, parameters, qf_result_fmt))
        return self._responses.pop(0)


def test_get_preview_and_index() -> None:
    mysql = FakeForgeQueryPort()
    mysql.query_mappings_responses = [
        [{"list_name": "ListA", "owner": "user1"}],
        [
            {
                "list_id": "list-1",
                "list_name": "ListA",
                "owner": "user1",
                "user_id": "user-1",
                "is_shared": 1,
                "created_at": date(2024, 1, 1),
                "updated_at": date(2024, 1, 2),
                "expires_at": None,
            }
        ],
    ]

    dbx = _FakeDBX(
        [
            {"table": _FakeTable([{"region": "NE"}])},
            {"rows": [{"total_rows": 1}]},
        ]
    )
    service = ForgeListReadService(mysql=mysql, dbx=dbx, workspace_id="ws1")

    preview = service.get_preview_by_id(list_type="regions", list_id="list-1", limit=1, offset=0)
    assert preview.rows[0]["region"] == "NE"

    index = service.get_index(qf_include_expired=True)
    assert index.regions[0].list_name == "ListA"
    assert index.regions[0].is_shared is True


def test_delete_list_success() -> None:
    mysql = FakeForgeQueryPort()
    dbx = _FakeDBX(
        [
            {
                "status": {"state": "SUCCEEDED"},
            }
        ]
    )
    service = ForgeListReadService(mysql=mysql, dbx=dbx, workspace_id="ws1")
    service.delete_list(list_type="regions", list_id="list-1")
    assert mysql.write_calls


def test_get_index_filters_by_user_visibility() -> None:
    mysql = FakeForgeQueryPort()
    mysql.query_mappings_responses = [[], [], []]
    dbx = _FakeDBX([])
    service = ForgeListReadService(mysql=mysql, dbx=dbx, workspace_id="ws1", user_id="user-1")

    service.get_index()

    assert len(mysql.query_mappings_calls) == 3
    first = mysql.query_mappings_calls[0]
    assert "user_id = :uid OR is_shared = 1" in first.query
    assert first.params["uid"] == "user-1"
    assert first.params["uid_is_null"] == 0


def test_get_preview_by_id_forbidden_when_not_visible() -> None:
    mysql = FakeForgeQueryPort()
    mysql.query_mappings_responses = [[]]
    dbx = _FakeDBX([])
    service = ForgeListReadService(mysql=mysql, dbx=dbx, workspace_id="ws1", user_id="user-1")

    with pytest.raises(ForgeError, match="List not found"):
        service.get_preview_by_id(list_type="regions", list_id="hidden", limit=10, offset=0)


def test_delete_list_requires_owner_when_user_context_present() -> None:
    mysql = FakeForgeQueryPort()
    mysql.query_mappings_responses = [[]]
    dbx = _FakeDBX([])
    service = ForgeListReadService(mysql=mysql, dbx=dbx, workspace_id="ws1", user_id="user-1")

    with pytest.raises(ForgeError, match="permission"):
        service.delete_list(list_type="regions", list_id="list-1")
