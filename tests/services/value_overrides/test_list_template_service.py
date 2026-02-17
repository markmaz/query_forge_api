from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services.value_overrides.list_template_service import ListTemplateService


def test_generate_template(monkeypatch) -> None:
    class FixedDatetime:
        @classmethod
        def now(cls, tz=None):
            return datetime(2024, 1, 2, tzinfo=timezone.utc)

    monkeypatch.setattr("app.services.value_overrides.list_template_service.datetime", FixedDatetime)

    service = ListTemplateService()
    result = service.generate_template("regions", include_time=False)
    assert result.filename.startswith("regions_template_2024-01-02")
    assert result.bytes


def test_col_letter() -> None:
    service = ListTemplateService()
    assert service._col_letter(1) == "A"
    assert service._col_letter(27) == "AA"


def test_unknown_template_type() -> None:
    service = ListTemplateService()
    with pytest.raises(ValueError):
        service.generate_template("unknown")  # type: ignore[arg-type]
