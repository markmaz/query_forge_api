from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services import base_service


class _Resp:
    def __init__(self, status_code: int, payload, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


def test_process_response_ok() -> None:
    resp = _Resp(200, {"ok": True})
    assert base_service.process_response(resp) == {"ok": True}


def test_process_response_error() -> None:
    resp = _Resp(500, {"error": "nope"}, text="boom")
    with pytest.raises(ForgeError):
        base_service.process_response(resp)


def test_build_url() -> None:
    assert base_service.build_url("https://a", "b", "c") == "https://a/b/c"
