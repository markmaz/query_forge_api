from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict, Optional

import pyarrow as pa
import pytest

from app.adapters.databricks_sql_executor import DatabricksSQLExecutor, _rows_from_result_json


class _Resp:
    def __init__(self, payload: Optional[Dict[str, Any]] = None, status_code: int = 200):
        self._payload = payload or {}
        self.status_code = status_code
        self.content = b""

    def json(self) -> Dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("status")


class _Session:
    def __init__(self):
        self.posts = []
        self.gets = []
        self._post_resp = _Resp()
        self._get_resp = _Resp()

    def set_post(self, resp: _Resp) -> None:
        self._post_resp = resp

    def set_get(self, resp: _Resp) -> None:
        self._get_resp = resp

    def post(self, url: str, headers: Dict[str, str], json: Optional[Dict[str, Any]] = None, timeout: int = 120):
        self.posts.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return self._post_resp

    def get(self, url: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None, timeout: int = 120):
        self.gets.append({"url": url, "headers": headers, "params": params, "timeout": timeout})
        return self._get_resp


class _TokenProvider:
    def __init__(self, token: str):
        self.token = token

    def get_token(self) -> str:
        return self.token


def test_encode_parameters() -> None:
    exec = DatabricksSQLExecutor(
        base_url="https://dbx",
        token_provider=_TokenProvider("tok"),
        http=_Session(),
        default_warehouse_id="wh",
    )

    values = {
        "n": None,
        "b": True,
        "i": 3,
        "f": 1.5,
        "dt": dt.datetime(2024, 1, 1, 12, 0, 0),
        "d": dt.date(2024, 1, 2),
        "s": "x",
    }
    out = exec._encode_parameters(values)
    by_name = {p["name"]: p for p in out}
    assert by_name["n"]["type"] == "NULL"
    assert by_name["b"]["type"] == "BOOLEAN"
    assert by_name["i"]["type"] == "INT"
    assert by_name["f"]["type"] == "DOUBLE"
    assert by_name["dt"]["type"] == "TIMESTAMP"
    assert by_name["d"]["type"] == "DATE"
    assert by_name["s"]["type"] == "STRING"


def test_headers_use_token() -> None:
    exec = DatabricksSQLExecutor(
        base_url="https://dbx",
        token_provider=_TokenProvider("tok"),
        http=_Session(),
        default_warehouse_id="wh",
    )
    headers = exec._headers()
    assert headers["Authorization"] == "Bearer tok"


def test_submit_statement_wait_false() -> None:
    session = _Session()
    session.set_post(_Resp({"statement_id": "s1"}))
    exec = DatabricksSQLExecutor(
        base_url="https://dbx",
        token_provider=_TokenProvider("tok"),
        http=session,
        default_warehouse_id="wh",
    )

    resp = exec.submit_statement("SELECT 1", wait=False, result_format="JSON_ARRAY")
    assert resp["statement_id"] == "s1"
    assert session.posts


def test_submit_statement_async_overrides() -> None:
    session = _Session()
    session.set_post(_Resp({"statement_id": "s2"}))
    exec = DatabricksSQLExecutor(
        base_url="https://dbx",
        token_provider=_TokenProvider("tok"),
        http=session,
        default_warehouse_id="wh-default",
        default_catalog="cat-default",
        default_schema="sch-default",
    )

    resp = exec.submit_statement_async(
        "SELECT 1",
        {"p1": 1},
        warehouse_id="wh-override",
        catalog="cat-override",
        schema="sch-override",
    )

    assert resp["statement_id"] == "s2"
    payload = session.posts[-1]["json"]
    assert payload["warehouse_id"] == "wh-override"
    assert payload["catalog"] == "cat-override"
    assert payload["schema"] == "sch-override"
    assert payload["statement"] == "SELECT 1"
    assert payload["parameters"]


def test_get_statement_status() -> None:
    session = _Session()
    session.set_get(_Resp({"status": {"state": "RUNNING"}}))
    exec = DatabricksSQLExecutor(
        base_url="https://dbx",
        token_provider=_TokenProvider("tok"),
        http=session,
        default_warehouse_id="wh",
    )

    status = exec.get_statement_status("s1")
    assert status["status"]["state"] == "RUNNING"


def test_cancel_statement_allows_202() -> None:
    session = _Session()
    session.set_post(_Resp(status_code=202))
    exec = DatabricksSQLExecutor(
        base_url="https://dbx",
        token_provider=_TokenProvider("tok"),
        http=session,
        default_warehouse_id="wh",
    )
    exec.cancel_statement("s1")


def test_submit_statement_arrow(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _Session()
    session.set_post(_Resp({"statement_id": "s1"}))
    exec = DatabricksSQLExecutor(
        base_url="https://dbx",
        token_provider=_TokenProvider("tok"),
        http=session,
        default_warehouse_id="wh",
    )

    monkeypatch.setattr(exec, "_wait_for_terminal", lambda stmt_id, timeout_s: {"status": {"state": "SUCCEEDED"}})
    monkeypatch.setattr(exec, "fetch_arrow_table", lambda stmt_id: pa.table({"a": [1]}))

    resp = exec.submit_statement("SELECT 1", result_format="ARROW_STREAM")
    assert resp["rows"] == [{"a": 1}]
    assert resp["result_format"] == "ARROW_STREAM"


def test_execute_write_failed() -> None:
    exec = DatabricksSQLExecutor(
        base_url="https://dbx",
        token_provider=_TokenProvider("tok"),
        http=_Session(),
        default_warehouse_id="wh",
    )

    exec.submit_statement = lambda *a, **k: {"status": {"state": "FAILED"}}
    with pytest.raises(RuntimeError):
        exec.execute_write("UPDATE t SET a=1")


def test_cancel_allows_404() -> None:
    session = _Session()
    session.set_post(_Resp(status_code=404))
    exec = DatabricksSQLExecutor(
        base_url="https://dbx",
        token_provider=_TokenProvider("tok"),
        http=session,
        default_warehouse_id="wh",
    )
    exec.cancel("s1")


def test_rows_from_result_json_inline() -> None:
    payload = {
        "result": {"data_array": [[1, "a"]]},
        "manifest": {"schema": {"columns": [{"name": "id"}, {"name": "name"}]}},
    }
    assert _rows_from_result_json(payload) == [{"id": 1, "name": "a"}]


def test_rows_from_result_json_list() -> None:
    payload = {"result": [{"a": 1}]}
    assert _rows_from_result_json(payload) == [{"a": 1}]


def test_submit_statement_logs_redacted_payload(caplog: pytest.LogCaptureFixture) -> None:
    session = _Session()
    session.set_post(_Resp({"statement_id": "s1"}))
    exec = DatabricksSQLExecutor(
        base_url="https://dbx",
        token_provider=_TokenProvider("tok"),
        http=session,
        default_warehouse_id="wh",
    )

    secret_sql = "SELECT * FROM users WHERE email='secret@example.com'"
    with caplog.at_level(logging.DEBUG, logger="app.adapters.databricks_sql_executor"):
        exec.submit_statement(secret_sql, parameters={"api_key": "shhh"}, wait=False)

    messages = [rec.message for rec in caplog.records]
    assert any("Submitting SQL statement" in msg for msg in messages)
    assert not any("secret@example.com" in msg for msg in messages)
    assert not any("shhh" in msg for msg in messages)
    assert any("statement_len" in msg for msg in messages)


def test_poll_status_logs_only_state(caplog: pytest.LogCaptureFixture) -> None:
    session = _Session()
    session.set_get(
        _Resp(
            {
                "status": {"state": "RUNNING"},
                "debug_payload": {"token": "secret-token", "sql": "SELECT secret"},
            }
        )
    )
    exec = DatabricksSQLExecutor(
        base_url="https://dbx",
        token_provider=_TokenProvider("tok"),
        http=session,
        default_warehouse_id="wh",
    )

    with caplog.at_level(logging.DEBUG, logger="app.adapters.databricks_sql_executor"):
        exec.poll_status("s1")

    messages = [rec.message for rec in caplog.records]
    assert any("Polled status for s1: state=RUNNING" in msg for msg in messages)
    assert not any("secret-token" in msg for msg in messages)
    assert not any("SELECT secret" in msg for msg in messages)
