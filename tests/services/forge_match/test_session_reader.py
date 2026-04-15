from __future__ import annotations

import pytest

import app.services.forge_match.session_reader as session_reader
from app.services.forge_match.session_reader import ForgeMatchSessionReader
from tests._support.fakes import FakeForgeQueryPort


def test_parse_json_dict_returns_none_for_invalid_json() -> None:
    assert session_reader._parse_json_dict("{not-json") is None
    assert session_reader._parse_json_dict('["not", "dict"]') is None


def test_parse_json_dict_surfaces_unexpected_parser_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_value):
        raise AssertionError("unexpected session reader parser bug")

    monkeypatch.setattr(session_reader.json, "loads", _boom)

    with pytest.raises(AssertionError, match="unexpected session reader parser bug"):
        session_reader._parse_json_dict('{"x":1}')


def test_get_session_row_returns_shaped_response() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[{"id": "sess-1", "workspace_id": "ws-1", "summary_json": '{"ok": true}'}]]

    out = ForgeMatchSessionReader(sql=sql).get_session_row(workspace_id="ws-1", session_id="sess-1")

    assert out["id"] == "sess-1"
    assert out["summary_json"] == {"ok": True}
