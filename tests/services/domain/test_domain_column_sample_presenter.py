from __future__ import annotations

import pytest

import app.services.domain.column_sample.domain_column_sample_presenter as domain_column_sample_presenter
from app.services.domain.column_sample.domain_column_sample_presenter import base_response, safe_json_load


def test_safe_json_load_parses_lists() -> None:
    assert safe_json_load("[1, 2]") == [1, 2]


def test_base_response_preserves_shape() -> None:
    out = base_response(
        workspace_table_id=1,
        full_name="main.asset.tbl",
        model_table_id=None,
        column_name="col",
        limit=10,
        values=["a"],
        sample_stats={"rows": 1},
        sample_ran_at=None,
        error=None,
    )

    assert out["workspace_table_id"] == 1
    assert out["column_name"] == "col"
    assert out["values"] == ["a"]


def test_safe_json_load_surfaces_unexpected_parser_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_value):
        raise AssertionError("unexpected sample presenter bug")

    monkeypatch.setattr(domain_column_sample_presenter.json, "loads", _boom)

    with pytest.raises(AssertionError, match="unexpected sample presenter bug"):
        safe_json_load("[1, 2]")
