from __future__ import annotations

from app.services.user.workspace_user_serializer import serialize_workspace_user_row


def test_serialize_workspace_user_row_normalizes_name_and_default_flag() -> None:
    out = serialize_workspace_user_row(
        {
            "user_id": "u1",
            "username": "alice",
            "email": "a@example.com",
            "first_name": "Alice",
            "last_name": "Smith",
            "status": "Active",
            "is_default": 1,
            "display_name": " Alice Smith ",
        }
    )

    assert out["user_id"] == "u1"
    assert out["is_default"] is True
    assert out["display_name"] == "Alice Smith"
