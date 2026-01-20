from __future__ import annotations

import pytest

from app.exceptions.service_error import ServiceError
from app.services.models.model_sample_read_service import ModelColumnSampleReadService
from tests._support.fakes import FakeSQLExecutor


def test_sample_column_values_validates_inputs() -> None:
    svc = ModelColumnSampleReadService(sql=FakeSQLExecutor())
    with pytest.raises(ServiceError):
        svc.sample_column_values(workspace_id="ws", user_id="u", domain_id=0, workspace_table_id=1, column_name="x")
    with pytest.raises(ServiceError):
        svc.sample_column_values(workspace_id="ws", user_id="u", domain_id=1, workspace_table_id=0, column_name="x")
    with pytest.raises(ServiceError):
        svc.sample_column_values(workspace_id="ws", user_id="u", domain_id=1, workspace_table_id=1, column_name="")


def test_sample_column_values_forbidden() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses.append([])
    svc = ModelColumnSampleReadService(sql=sql)

    with pytest.raises(ServiceError):
        svc.sample_column_values(workspace_id="ws", user_id="u", domain_id=1, workspace_table_id=2, column_name="x")


def test_sample_column_values_missing_model_table_id() -> None:
    sql = FakeSQLExecutor()
    sql.query_mappings_responses.append([{"model_table_id": None}])
    svc = ModelColumnSampleReadService(sql=sql)

    with pytest.raises(ServiceError):
        svc.sample_column_values(workspace_id="ws", user_id="u", domain_id=1, workspace_table_id=2, column_name="x")
