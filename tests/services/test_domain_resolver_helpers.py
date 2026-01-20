from __future__ import annotations

import pytest

from app.exceptions.service_error import ServiceError
from app.services.domain_resolver import _safe_fqn


def test_safe_fqn_accepts_two_or_three_parts():
    assert _safe_fqn("schema.table") == "schema.table"
    assert _safe_fqn("catalog.schema.table") == "catalog.schema.table"


def test_safe_fqn_rejects_invalid():
    with pytest.raises(ServiceError):
        _safe_fqn("bad name")

    with pytest.raises(ServiceError):
        _safe_fqn("a.b.c.d")
