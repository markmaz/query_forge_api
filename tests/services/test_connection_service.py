from __future__ import annotations

from app.services.connection_service import ConnectionService, convert_to_conn


class _Resp:
    def __init__(self, status_code: int, payload=None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = "text"

    def json(self):
        return self._payload


def test_convert_to_conn() -> None:
    data = {"host": "host", "connectionId": "c1", "name": "Conn", "useOauth": False}
    conn = convert_to_conn(data)
    assert conn.connection_id == "c1"


def test_get_connections(monkeypatch) -> None:
    monkeypatch.setattr("app.services.connection_service.get_headers", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("app.services.connection_service.requests.get", lambda *_args, **_kwargs: _Resp(200))
    monkeypatch.setattr(
        "app.services.connection_service.process_response",
        lambda _resp: {"entries": [{"host": "h", "connectionId": "c1", "name": "Org-One", "useOauth": True}]},
    )
    svc = ConnectionService()
    rows = svc.get_connections()
    assert rows[0]["connection_id"] == "c1"


def test_get_connection_by_filters(monkeypatch) -> None:
    svc = ConnectionService()
    monkeypatch.setattr(
        ConnectionService,
        "get_connections",
        lambda *_args, **_kwargs: [
            {"host": "alpha", "name": "Org-One"},
            {"host": "beta", "name": "Other"},
        ],
    )
    assert svc.get_connection_by_org("Org") == [{"host": "alpha", "name": "Org-One"}]
    assert svc.get_connection_by_host("beta") == [{"host": "beta", "name": "Other"}]


def test_get_connection_by_id(monkeypatch) -> None:
    monkeypatch.setattr("app.services.connection_service.get_headers", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("app.services.connection_service.requests.get", lambda *_args, **_kwargs: _Resp(200))
    monkeypatch.setattr(
        "app.services.connection_service.process_response",
        lambda _resp: {"host": "h", "connectionId": "c1", "name": "Org", "useOauth": False},
    )
    svc = ConnectionService()
    conn = svc.get_connection_by_id("c1")
    assert conn["connection_id"] == "c1"


def test_create_connection_is_placeholder() -> None:
    svc = ConnectionService()
    assert svc.create_connection(None) is None
