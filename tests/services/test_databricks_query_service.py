from __future__ import annotations

import importlib
import json
from typing import Any, Dict, List

import pytest

import app.services.base_token_manager as base_token_manager


class _Resp:
    def __init__(self, payload: Dict[str, Any], status_code: int = 200, content: bytes | None = None):
        self._payload = payload
        self.status_code = status_code
        self.content = content or b""

    def json(self) -> Dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("status")


class _Session:
    def __init__(self):
        self.posts: List[Dict[str, Any]] = []
        self.gets: List[str] = []
        self._queue: List[_Resp] = []

    def queue(self, *resp: _Resp) -> None:
        self._queue.extend(resp)

    def post(self, url: str, data: str) -> _Resp:
        self.posts.append({"url": url, "data": data})
        return self._queue.pop(0)

    def get(self, url: str) -> _Resp:
        self.gets.append(url)
        return self._queue.pop(0)


@pytest.fixture
def dqs(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(base_token_manager, "forge_auth_headers", lambda token_manager=None: {})
    mod = importlib.import_module("app.services.databricks_query_service")
    importlib.reload(mod)
    return mod


def test_submit_statement_builds_payload(monkeypatch: pytest.MonkeyPatch, dqs) -> None:
    session = _Session()
    session.queue(_Resp({"qf_statement_id": "s1"}))
    monkeypatch.setattr(dqs, "s", session)

    resp = dqs.submit_statement(
        "SELECT 1",
        databricks_host="https://dbx",
        warehouse_id="wh",
        catalog="cat",
        schema="sch",
        disposition="INLINE",
        fmt="JSON_ARRAY",
        wait_timeout="5s",
    )

    assert resp["qf_statement_id"] == "s1"
    payload = json.loads(session.posts[0]["data"])
    assert payload["warehouse_id"] == "wh"
    assert payload["statement"] == "SELECT 1"
    assert payload["catalog"] == "cat"
    assert payload["schema"] == "sch"
    assert payload["disposition"] == "INLINE"
    assert payload["format"] == "JSON_ARRAY"
    assert payload["wait_timeout"] == "5s"


def test_wait_until_done_succeeds(monkeypatch: pytest.MonkeyPatch, dqs) -> None:
    statuses = [
        {"status": {"state": "RUNNING"}},
        {"status": {"state": "SUCCEEDED"}},
    ]

    def _get(stmt_id: str) -> Dict[str, Any]:
        return statuses.pop(0)

    monkeypatch.setattr(dqs, "get_statement", _get)

    final = dqs.wait_until_done("s1", qf_poll_interval=0.0, qf_timeout_s=1.0)
    assert final["status"]["state"] == "SUCCEEDED"


def test_wait_until_done_timeout(monkeypatch: pytest.MonkeyPatch, dqs) -> None:
    monkeypatch.setattr(dqs, "get_statement", lambda stmt_id: {"status": {"state": "RUNNING"}})
    with pytest.raises(TimeoutError):
        dqs.wait_until_done("s1", qf_poll_interval=0.0, qf_timeout_s=0.0)


def test_iter_inline_chunks_follows_next(monkeypatch: pytest.MonkeyPatch, dqs) -> None:
    session = _Session()
    session.queue(
        _Resp({"result": {"data_array": [[3]]}}),
    )
    monkeypatch.setattr(dqs, "s", session)

    first = {"result": {"data_array": [[1], [2]]}, "next_chunk_internal_link": "/chunk/1"}
    chunks = list(dqs.iter_inline_chunks(first, "https://dbx"))
    assert chunks == [[[1], [2]], [[3]]]
    assert session.gets[0] == "https://dbx/chunk/1"


def test_download_external_link(monkeypatch: pytest.MonkeyPatch, dqs) -> None:
    def _get(url: str, timeout: int = 120):
        return _Resp({}, content=b"payload")

    monkeypatch.setattr(dqs.requests, "get", _get)
    assert dqs.download_external_link("https://link") == b"payload"


def test_iter_external_links_handles_inline_fallback(monkeypatch: pytest.MonkeyPatch, dqs) -> None:
    session = _Session()
    session.queue(
        _Resp({"result": {"data_array": [[1]]}}),
    )
    monkeypatch.setattr(dqs, "s", session)

    manifest = {"total_chunk_count": 1}
    payloads = list(dqs.iter_external_links("stmt-1", manifest, "https://dbx"))
    assert payloads == [b"[[1]]"]


def test_run_and_collect_all_inline(monkeypatch: pytest.MonkeyPatch, dqs) -> None:
    monkeypatch.setattr(dqs, "submit_statement", lambda *a, **k: {"qf_statement_id": "s1"})
    monkeypatch.setattr(dqs, "wait_until_done", lambda stmt_id: {"status": {"state": "SUCCEEDED"}})
    monkeypatch.setattr(dqs, "iter_inline_chunks", lambda resp: [[{"a": 1}], [{"a": 2}]])

    rows = dqs.run_and_collect_all("SELECT 1", disposition="INLINE", fmt="JSON_ARRAY")
    assert rows == [{"a": 1}, {"a": 2}]


def test_run_and_collect_all_external_json(monkeypatch: pytest.MonkeyPatch, dqs) -> None:
    monkeypatch.setattr(dqs, "submit_statement", lambda *a, **k: {"qf_statement_id": "s1"})
    monkeypatch.setattr(dqs, "wait_until_done", lambda stmt_id: {"status": {"state": "SUCCEEDED"}, "manifest": {}})
    monkeypatch.setattr(dqs, "iter_external_links", lambda stmt_id, manifest: [b"[{\"a\": 1}]"])

    rows = dqs.run_and_collect_all("SELECT 1", disposition="EXTERNAL_LINKS", fmt="JSON_ARRAY")
    assert rows == [{"a": 1}]


def test_run_and_collect_all_external_raw(monkeypatch: pytest.MonkeyPatch, dqs) -> None:
    monkeypatch.setattr(dqs, "submit_statement", lambda *a, **k: {"qf_statement_id": "s1"})
    monkeypatch.setattr(dqs, "wait_until_done", lambda stmt_id: {"status": {"state": "SUCCEEDED"}, "manifest": {}})
    monkeypatch.setattr(dqs, "iter_external_links", lambda stmt_id, manifest: [b"a", b"b"])

    raw = dqs.run_and_collect_all("SELECT 1", disposition="EXTERNAL_LINKS", fmt="CSV")
    assert raw == [b"a", b"b"]
