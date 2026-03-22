from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("PUT", "/api/v1/users/u1", {"username": "u"}),
    ],
)
def test_mutating_routes_require_auth(client, method: str, path: str, payload):
    kwargs = {"method": method, "path": path}
    if payload is not None:
        kwargs["json"] = payload

    resp = client.open(**kwargs)
    assert resp.status_code == 403
