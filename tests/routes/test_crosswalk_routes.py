from __future__ import annotations

from datetime import datetime, timezone

import app.routes.crosswalk_routes as crosswalk_routes
from app.models.crosswalk import CrosswalkListIndex, CrosswalkMeta


def test_crosswalk_visibility_success(client, auth_headers, monkeypatch):
    calls = {"include_expired": None}

    class _Result:
        def __init__(self):
            self.index = CrosswalkListIndex(
                regions=[
                    CrosswalkMeta(
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

        def get_index(self, *, include_expired: bool = False):
            calls["include_expired"] = include_expired
            return _Result()

    monkeypatch.setattr(crosswalk_routes, "CrosswalkVisibilityService", _Svc)

    resp = client.get("/api/v1/crosswalks/visibility?include_expired=1", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json["hasShared"] is True
    assert resp.json["index"]["regions"][0]["listName"] == "List A"
    assert resp.json["index"]["regions"][0]["listType"] == "regions"
    assert calls["include_expired"] is True
