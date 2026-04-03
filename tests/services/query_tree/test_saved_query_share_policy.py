from __future__ import annotations

import datetime

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.query_tree.saved_query_share_policy import (
    build_share_list_item,
    build_share_payload,
    require_field,
)


def test_require_field_rejects_blank_values():
    with pytest.raises(ForgeError):
        require_field("", "field")


def test_require_field_strips_values():
    assert require_field(" value ", "field") == "value"


def test_build_share_payload_sets_can_edit():
    out = build_share_payload(
        acl_id="a1",
        query_id="q1",
        principal_type="USER",
        principal_id="user-2",
        permission="WRITE",
    )

    assert out["canEdit"] is True
    assert out["principalType"] == "USER"


def test_build_share_list_item_formats_created_at():
    created_at = datetime.datetime(2024, 1, 2, 3, 4, 5)

    out = build_share_list_item(
        {
            "id": "a1",
            "principal_type": "WORKSPACE",
            "principal_id": "ws",
            "permission": "READ",
            "created_at": created_at,
        }
    )

    assert out["createdAt"] == created_at.isoformat()
    assert out["canEdit"] is False
