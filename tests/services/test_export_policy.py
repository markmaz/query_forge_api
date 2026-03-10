from __future__ import annotations

from app.services.exports.export_policy import (
    QF_EXCEL_MAX_ROWS,
    build_qf_export_policy,
    clear_qf_rowcount_cache,
    fetch_cached_rowcount,
    qf_rowcount_signature,
    store_cached_rowcount,
)


def test_export_policy_allowed():
    policy = build_qf_export_policy(QF_EXCEL_MAX_ROWS)
    assert policy["excel"]["allowed"] is True
    assert policy["excel"]["reason"] is None


def test_export_policy_blocked():
    policy = build_qf_export_policy(QF_EXCEL_MAX_ROWS + 1)
    assert policy["excel"]["allowed"] is False
    assert policy["excel"]["reason"] == "EXCEL_ROW_LIMIT"


def test_rowcount_cache_roundtrip():
    clear_qf_rowcount_cache()
    signature = qf_rowcount_signature("select 1", {"b": 2, "a": 1})
    store_cached_rowcount(signature, 123)
    assert fetch_cached_rowcount(signature) == 123
