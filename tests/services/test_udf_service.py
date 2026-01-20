from __future__ import annotations

import json

from app.services.udf_service import UdfService


class _Resp:
    def __init__(self, status_code: int, payload=None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = "text"

    def json(self):
        return self._payload


def test_get_diag_code_details(monkeypatch) -> None:
    monkeypatch.setattr("app.services.udf_service.get_headers", lambda *_args, **_kwargs: {})
    monkeypatch.setattr("app.services.udf_service.requests.post", lambda *_a, **_k: _Resp(200))
    monkeypatch.setattr(
        "app.services.udf_service.process_response",
        lambda _resp: {"result": {"data_array": [[json.dumps({"a": 1})]]}},
    )
    svc = UdfService()
    assert svc.get_diag_code_details("A1") == {"a": 1}
