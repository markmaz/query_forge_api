from __future__ import annotations

from app.services.planner.value_normalizers.country import normalize_country_values


def test_country_normalize_iso2_direct() -> None:
    assert normalize_country_values("us") == ["US"]
    assert normalize_country_values("MX") == ["MX"]


def test_country_normalize_name() -> None:
    assert normalize_country_values("United States") == ["US"]


def test_country_normalize_punct() -> None:
    assert normalize_country_values("U.S.") == ["US"]


def test_country_normalize_code3() -> None:
    assert normalize_country_values("USA") == ["US"]


def test_country_normalize_list_dedupe() -> None:
    assert normalize_country_values(["US", "United States", "u.s."]) == ["US"]


def test_country_normalize_unknown() -> None:
    assert normalize_country_values("Wakanda") == []
