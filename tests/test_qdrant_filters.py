from __future__ import annotations

from qdrant_client.http import models as qdrant_models

from app.infra.qdrant_client import build_payload_filter


def test_build_payload_filter_with_workspace_table_ids() -> None:
    filt = build_payload_filter(
        kinds=["column"],
        workspace_id="ws1",
        workspace_table_ids=[1, 2, 3],
    )
    assert isinstance(filt, qdrant_models.Filter)
    keys = [cond.key for cond in filt.must]
    assert "workspace_id" in keys
    assert "workspace_table_id" in keys

    ws_cond = next(cond for cond in filt.must if cond.key == "workspace_table_id")
    assert isinstance(ws_cond.match, qdrant_models.MatchAny)
    assert ws_cond.match.any == [1, 2, 3]
