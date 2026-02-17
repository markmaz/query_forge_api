from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from app.exceptions.service_error import ServiceError
from app.services import warehouse_service
from app.services.warehouse_service import WarehouseService, get_server_name, parse_warehouse_list


class _Resp:
    def __init__(self, status_code: int, payload=None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = "text"

    def json(self):
        return self._payload


def test_parse_warehouse_list() -> None:
    data = {
        "warehouses": [
            {
                "id": "w1",
                "name": "WH1",
                "cluster_size": "2X-Small",
                "auto_stop_mins": 10,
                "min_num_clusters": 1,
                "max_num_clusters": 2,
                "enable_serverless_compute": False,
                "warehouse_type": "PRO",
            }
        ]
    }
    out = parse_warehouse_list(data)
    assert out[0]["warehouse_id"] == "w1"


def test_get_server_name_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        warehouse_service,
        "get_workspace",
        lambda _ws: SimpleNamespace(server="https://dbx"),
    )
    assert get_server_name("ws") == "https://dbx"


def test_get_server_name_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(warehouse_service, "get_workspace", lambda _ws: SimpleNamespace(server=None))
    with pytest.raises(ServiceError):
        get_server_name("ws")


def test_get_warehouse_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = WarehouseService()
    monkeypatch.setattr(
        WarehouseService,
        "get_all_warehouses",
        lambda *_args, **_kwargs: [{"name": "Primary", "warehouse_id": "w1"}],
    )
    wh = svc.get_warehouse_by_name(workspace_id="ws", warehouse_name="primary")
    assert wh["warehouse_id"] == "w1"


def test_get_warehouse_by_name_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = WarehouseService()
    monkeypatch.setattr(WarehouseService, "get_all_warehouses", lambda *_args, **_kwargs: [])
    with pytest.raises(ServiceError):
        svc.get_warehouse_by_name(workspace_id="ws", warehouse_name="missing")


def test_get_warehouses_for_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(warehouse_service, "get_server_name", lambda _ws: "https://dbx")
    monkeypatch.setattr("app.services.warehouse_service.get_headers", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("app.services.warehouse_service.requests.get", lambda *_a, **_k: _Resp(200))
    monkeypatch.setattr(
        "app.services.warehouse_service.process_response",
        lambda _resp: {
            "id": "w1",
            "name": "WH1",
            "cluster_size": "2X-Small",
            "auto_stop_mins": 10,
            "min_num_clusters": 1,
            "max_num_clusters": 2,
            "enable_serverless_compute": False,
            "warehouse_type": "PRO",
        },
    )
    svc = WarehouseService()
    wh = svc.get_warehouses_for_workspace(workspace_id="ws", warehouse_id="w1")
    assert wh["warehouse_id"] == "w1"


def test_get_all_warehouses_does_not_log_auth_header(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(warehouse_service, "get_server_name", lambda _ws: "https://dbx")
    monkeypatch.setattr(
        "app.services.warehouse_service.get_headers",
        lambda *_args, **_kwargs: {"Authorization": "Bearer super-secret"},
    )
    monkeypatch.setattr("app.services.warehouse_service.requests.get", lambda *_a, **_k: _Resp(200))
    monkeypatch.setattr(
        "app.services.warehouse_service.process_response",
        lambda _resp: {"warehouses": []},
    )
    svc = WarehouseService()
    with caplog.at_level(logging.DEBUG, logger="app.services.warehouse_service"):
        svc.get_all_warehouses("ws-1")
    assert not any("super-secret" in rec.message for rec in caplog.records)
