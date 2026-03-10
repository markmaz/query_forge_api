from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.models.model_sample_read_service import ModelColumnSampleReadService
from tests._support.fakes import FakeForgeQueryPort


def test_sample_column_values_validates_inputs() -> None:
    svc = ModelColumnSampleReadService(sql=FakeForgeQueryPort())
    with pytest.raises(ForgeError):
        svc.sample_column_values(workspace_id="ws", user_id="u", domain_id=0, workspace_table_id=1, column_name="x")
    with pytest.raises(ForgeError):
        svc.sample_column_values(workspace_id="ws", user_id="u", domain_id=1, workspace_table_id=0, column_name="x")
    with pytest.raises(ForgeError):
        svc.sample_column_values(workspace_id="ws", user_id="u", domain_id=1, workspace_table_id=1, column_name="")


def test_sample_column_values_forbidden() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses.append([])
    svc = ModelColumnSampleReadService(sql=sql)

    with pytest.raises(ForgeError):
        svc.sample_column_values(workspace_id="ws", user_id="u", domain_id=1, workspace_table_id=2, column_name="x")


def test_sample_column_values_missing_model_table_id() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses.append([{"model_table_id": None}])
    svc = ModelColumnSampleReadService(sql=sql)

    with pytest.raises(ForgeError):
        svc.sample_column_values(workspace_id="ws", user_id="u", domain_id=1, workspace_table_id=2, column_name="x")
