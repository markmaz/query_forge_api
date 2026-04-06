from __future__ import annotations

import pytest

from app.services.planner.semantic_retrieval_helpers import to_int


def test_to_int_returns_none_for_invalid_integer_values() -> None:
    assert to_int("bad") is None
    assert to_int(None) is None


def test_to_int_surfaces_unexpected_integer_conversion_errors() -> None:
    class _BrokenInt:
        def __int__(self) -> int:
            raise AssertionError("unexpected retrieval helper conversion failure")

    with pytest.raises(AssertionError, match="unexpected retrieval helper conversion failure"):
        to_int(_BrokenInt())
