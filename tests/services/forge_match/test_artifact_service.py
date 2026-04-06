from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.forge_match.artifact_service import ForgeMatchArtifactService


def _service(*, submit_side_effect=None):
    class _Exec:
        def submit_statement(self, sql, **kwargs):
            del sql, kwargs
            if submit_side_effect is not None:
                raise submit_side_effect
            return {"status": {"state": "SUCCEEDED"}, "rows": []}

    return ForgeMatchArtifactService(
        session_reader=SimpleNamespace(
            get_session_row=lambda **kwargs: {"id": kwargs["session_id"]},
            accepted_columns=lambda **kwargs: [],
        ),
        view_draft_builder=SimpleNamespace(build_view_draft_sql_preview=lambda **kwargs: {}),
        exporter=SimpleNamespace(export_session=lambda **kwargs: (b"", "x.csv", "text/csv")),
        workspace_context_builder_factory=lambda: SimpleNamespace(build=lambda _ws: SimpleNamespace(sql_exec=_Exec())),
    )


def test_execute_view_draft_sql_wraps_expected_runtime_errors() -> None:
    svc = _service(submit_side_effect=RuntimeError("statement failed"))

    with pytest.raises(ForgeError, match="Draft SQL execution failed: statement failed"):
        svc.execute_view_draft_sql(
            workspace_id="ws-1",
            session_id="sess-1",
            sql="SELECT 1",
        )


def test_execute_view_draft_sql_surfaces_unexpected_execution_errors() -> None:
    svc = _service(submit_side_effect=AssertionError("unexpected execution bug"))

    with pytest.raises(AssertionError, match="unexpected execution bug"):
        svc.execute_view_draft_sql(
            workspace_id="ws-1",
            session_id="sess-1",
            sql="SELECT 1",
        )
