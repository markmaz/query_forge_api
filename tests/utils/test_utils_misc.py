from __future__ import annotations

from flask import g

from app.services.shared.request_context import get_current_username
from app.utils.param_builder import ParamBuilder
from app.utils.token_utils import generate_token, validate_token


def test_param_builder() -> None:
    builder = ParamBuilder()
    assert str(builder) == ""
    builder.add_param("foo", "bar")
    builder.add_param("baz", "a b", encode=True)
    assert builder.get_query_string().startswith("?")
    assert ":foo=bar" in builder.get_query_string()


def test_token_utils_round_trip() -> None:
    token = generate_token("user-1")
    assert validate_token(token, max_age_seconds=10) == "user-1"


def test_get_current_username(app) -> None:
    with app.app_context():
        assert get_current_username() == "unknown_user"
        g.user_data = {"username": "alice"}
        assert get_current_username() == "alice"
        g.user_data = {"sub": "bob"}
        assert get_current_username() == "bob"
