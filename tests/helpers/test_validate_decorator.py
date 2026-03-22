from __future__ import annotations

import pytest

from app.utils.param_guard import validate_params
from app.exceptions.forge_error import ForgeError


class _Dummy:
    @validate_params("a", "b")
    def func(self, *, a=None, b=None):
        return {"a": a, "b": b}


@validate_params("password")
def _validate_password(password=None):
    return password


def test_validate_params_missing() -> None:
    with pytest.raises(ForgeError):
        _Dummy().func(a="1")


def test_validate_params_success() -> None:
    assert _Dummy().func(a="1", b="2") == {"a": "1", "b": "2"}


def test_validate_params_plain_function_positional_success() -> None:
    assert _validate_password("abc123") == "abc123"


def test_validate_params_plain_function_missing() -> None:
    with pytest.raises(ForgeError):
        _validate_password()
