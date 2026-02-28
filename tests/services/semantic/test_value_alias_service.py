from __future__ import annotations

from app.services.semantic.value_alias_service import canonicalize_value


def test_canonicalize_race_aliases() -> None:
    assert canonicalize_value("RACE", "black") == "Black - African American"
    assert canonicalize_value("RACE", "african american") == "Black - African American"
    assert canonicalize_value("RACE", "african-american") == "Black - African American"
    assert canonicalize_value("RACE", "African American students") == "Black - African American"


def test_canonicalize_unknown_value_returns_none() -> None:
    assert canonicalize_value("RACE", "martian") is None
