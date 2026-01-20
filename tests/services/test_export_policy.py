from __future__ import annotations

from app.services.exports.export_policy import (
    EXCEL_MAX_ROWS,
    build_export_policy,
    clear_rowcount_cache,
    get_cached_rowcount,
    make_rowcount_signature,
    set_cached_rowcount,
)


def test_export_policy_allowed():
    policy = build_export_policy(EXCEL_MAX_ROWS)
    assert policy["excel"]["allowed"] is True
    assert policy["excel"]["reason"] is None


def test_export_policy_blocked():
    policy = build_export_policy(EXCEL_MAX_ROWS + 1)
    assert policy["excel"]["allowed"] is False
    assert policy["excel"]["reason"] == "EXCEL_ROW_LIMIT"


def test_rowcount_cache_roundtrip():
    clear_rowcount_cache()
    signature = make_rowcount_signature("select 1", {"b": 2, "a": 1})
    set_cached_rowcount(signature, 123)
    assert get_cached_rowcount(signature) == 123
