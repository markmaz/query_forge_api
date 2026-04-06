from __future__ import annotations

import pytest

from app.services.llm.io_logging import _to_log_text


def test_to_log_text_falls_back_for_expected_json_serialization_errors() -> None:
    value = {object(): "alpha"}

    text = _to_log_text(value)

    assert text.startswith("{")
    assert "alpha" in text


def test_to_log_text_surfaces_unexpected_string_conversion_errors() -> None:
    class _BrokenValue:
        def __str__(self) -> str:
            raise AssertionError("unexpected string conversion failure")

    with pytest.raises(AssertionError, match="unexpected string conversion failure"):
        _to_log_text(_BrokenValue())
