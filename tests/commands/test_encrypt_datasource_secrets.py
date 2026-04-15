from __future__ import annotations

from unittest.mock import patch

import pytest

from app.commands.encrypt_datasource_secrets import _coerce_json_obj


def test_coerce_json_obj_returns_empty_dict_for_invalid_json() -> None:
    assert _coerce_json_obj("{not-json}") == {}


def test_coerce_json_obj_surfaces_unexpected_json_parser_errors() -> None:
    with patch("app.commands.encrypt_datasource_secrets.json.loads", side_effect=AssertionError("unexpected json bug")):
        with pytest.raises(AssertionError, match="unexpected json bug"):
            _coerce_json_obj('{"valid": true}')
