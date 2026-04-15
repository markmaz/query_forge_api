from __future__ import annotations

from datetime import datetime

from app.services.execution.execution_status_helpers import utc_now_iso


def test_utc_now_iso_returns_z_suffix_without_fractional_seconds() -> None:
    out = utc_now_iso()

    assert out.endswith("Z")
    assert "." not in out
    parsed = datetime.fromisoformat(out.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
