from __future__ import annotations

import pytest

from app.services.semantic.semantic_card_service import (
    _derive_signals,
    _is_year_or_date,
    _parse_json_any,
)


def test_parse_json_any_returns_none_for_invalid_json_text() -> None:
    assert _parse_json_any("{not-json}") is None


def test_derive_signals_ignores_invalid_unique_ratio_values() -> None:
    signals = _derive_signals(samples=["A", "B"], stats={"unique_ratio_estimate": "not-a-number"})

    assert signals["unique_ratio_estimate"] is None


def test_derive_signals_surfaces_unexpected_unique_ratio_errors() -> None:
    class _BadFloat:
        def __float__(self) -> float:
            raise RuntimeError("bad ratio conversion")

    with pytest.raises(RuntimeError, match="bad ratio conversion"):
        _derive_signals(samples=["A"], stats={"unique_ratio_estimate": _BadFloat()})


def test_is_year_or_date_returns_false_for_invalid_date_string() -> None:
    assert _is_year_or_date("not-a-date") is False
