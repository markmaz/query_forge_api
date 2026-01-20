from __future__ import annotations

import pytest

from app.decorators.validate import validate_params
from app.exceptions.service_error import ServiceError


class _Dummy:
    @validate_params("a", "b")
    def func(self, *, a=None, b=None):
        return {"a": a, "b": b}


def test_validate_params_missing() -> None:
    with pytest.raises(ServiceError):
        _Dummy().func(a="1")


def test_validate_params_success() -> None:
    assert _Dummy().func(a="1", b="2") == {"a": "1", "b": "2"}
