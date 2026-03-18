from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("PUT", "/api/v1/users/u1", {"username": "u"}),
        ("DELETE", "/api/v1/products/p1", None),
        ("PUT", "/api/v1/products/p1", {"product_name": "x"}),
        ("POST", "/api/v1/product-groups/", {"product_group_name": "g"}),
        ("PUT", "/api/v1/product-groups/g1/products/p1", None),
    ],
)
def test_mutating_routes_require_auth(client, method: str, path: str, payload):
    kwargs = {"method": method, "path": path}
    if payload is not None:
        kwargs["json"] = payload

    resp = client.open(**kwargs)
    assert resp.status_code == 403
