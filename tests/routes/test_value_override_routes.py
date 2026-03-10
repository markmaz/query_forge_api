from __future__ import annotations

from datetime import datetime, timezone

import app.routes.value_override_routes as value_override_routes
import app.decorators.security as security
from app.exceptions.forge_error import ForgeError
from app.models.value_override import ValueOverrideListIndex, ValueOverrideMeta


def _headers_with_auth(monkeypatch):
    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": "user-1", "username": "user-1"},
    )
    monkeypatch.setattr(
        security.workspace_access_service,
        "assert_workspace_access",
        lambda **kwargs: kwargs["workspace_id"],
    )
    return {"Authorization": "Bearer token-1", "X-Workspace-Id": "ws-1"}


def test_value_override_visibility_success(client, monkeypatch):
    calls = {"qf_include_expired": None}

    class _Result:
        def __init__(self):
            self.index = ValueOverrideListIndex(
                regions=[
                    ValueOverrideMeta(
                        list_id="list-1",
                        list_name="List A",
                        owner="alice",
                        user_id="user-1",
                        is_shared=True,
                        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                        updated_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
                        row_count=2,
                        expires_at=None,
                    )
                ]
            )
            self.has_shared = True

    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def get_index(self, *, qf_include_expired: bool = False):
            calls["qf_include_expired"] = qf_include_expired
            return _Result()

    monkeypatch.setattr(value_override_routes, "ValueOverrideVisibilityService", _Svc)

    resp = client.get(
        "/api/v1/value_overrides/visibility?qf_include_expired=1",
        headers=_headers_with_auth(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["hasShared"] is True
    assert resp.json["index"]["regions"][0]["listName"] == "List A"
    assert resp.json["index"]["regions"][0]["listType"] == "regions"
    assert calls["qf_include_expired"] is True


def test_value_override_patch_forbidden_when_not_owner(client, monkeypatch):
    class _Reader:
        def assert_owner(self, **_kwargs):
            raise ForgeError("You do not have permission to modify this list", status_code=403)

    class _MetaWriter:
        def set_shared(self, **_kwargs):
            raise AssertionError("set_shared should not run when unauthorized")

    class _Ctx:
        workspace_id = "ws-1"
        qf_list_reader = _Reader()
        meta_writer = _MetaWriter()

    monkeypatch.setattr(value_override_routes, "_build_databricks_context", lambda: _Ctx())

    resp = client.patch(
        "/api/v1/value_overrides/regions/list-1",
        headers=_headers_with_auth(monkeypatch),
        json={"isShared": True},
    )
    assert resp.status_code == 403


def test_value_override_delete_forbidden_when_not_owner(client, monkeypatch):
    class _Reader:
        def assert_owner(self, **_kwargs):
            raise ForgeError("You do not have permission to modify this list", status_code=403)

        def delete_list(self, **_kwargs):
            raise AssertionError("delete_list should not run when unauthorized")

    class _MetaWriter:
        def delete_meta(self, **_kwargs):
            raise AssertionError("delete_meta should not run when unauthorized")

    class _Ctx:
        workspace_id = "ws-1"
        qf_list_reader = _Reader()
        meta_writer = _MetaWriter()

    monkeypatch.setattr(value_override_routes, "_build_databricks_context", lambda: _Ctx())

    resp = client.delete(
        "/api/v1/value_overrides/regions/list-1",
        headers=_headers_with_auth(monkeypatch),
    )
    assert resp.status_code == 403
