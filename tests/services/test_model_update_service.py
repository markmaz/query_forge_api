from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeExecResult
from app.services.models.model_update_service import ModelUpdateService
from tests._support.fakes import FakeForgeQueryPort


def test_patch_column_rejects_invalid_fields():
    svc = ModelUpdateService(sql=FakeForgeQueryPort())
    with pytest.raises(ForgeError):
        svc.patch_column(column_id=1, patch={"nope": "x"})


def test_patch_column_requires_sets():
    svc = ModelUpdateService(sql=FakeForgeQueryPort())
    with pytest.raises(ForgeError):
        svc.patch_column(column_id=1, patch={})


def test_patch_column_success():
    fake = FakeForgeQueryPort()
    fake.write_responses = [1]
    fake.query_responses = [[(1, 10, "patients", "id", "INT", "desc", 1)]]
    svc = ModelUpdateService(sql=fake)
    result = svc.patch_column(column_id=1, patch={"dataType": "INT", "isActive": True})
    assert result["columnName"] == "id"
    assert result["isActive"] is True


def test_patch_column_not_found():
    fake = FakeForgeQueryPort()
    fake.write_responses = [0]
    svc = ModelUpdateService(sql=fake)
    with pytest.raises(ForgeError):
        svc.patch_column(column_id=99, patch={"description": "x"})


def test_patch_column_missing_after_update():
    fake = FakeForgeQueryPort()
    fake.write_responses = [1]
    fake.query_responses = [[]]
    svc = ModelUpdateService(sql=fake)
    with pytest.raises(ForgeError):
        svc.patch_column(column_id=99, patch={"description": "x"})


def test_create_column_creates_table():
    fake = FakeForgeQueryPort()
    fake.query_mappings_responses = [
        [],
        [
            {
                "id": 5,
                "logicalTableId": 2,
                "tableName": "patients",
                "columnName": "age",
                "dataType": "INT",
                "description": None,
                "isActive": 1,
            }
        ],
    ]
    fake.insert_responses = [ForgeExecResult(rowcount=1, lastrowid=2), ForgeExecResult(rowcount=1, lastrowid=5)]
    svc = ModelUpdateService(sql=fake)
    result = svc.create_column(
        table_name="patients",
        column_name="age",
        data_type="INT",
        description=None,
        is_active=True,
        created_by="user",
    )
    assert result["columnName"] == "age"


def test_create_column_existing_table():
    fake = FakeForgeQueryPort()
    fake.query_mappings_responses = [
        [{"id": 7, "name": "visits"}],
        [
            {
                "id": 9,
                "logicalTableId": 7,
                "tableName": "visits",
                "columnName": "visit_id",
                "dataType": "INT",
                "description": None,
                "isActive": 1,
            }
        ],
    ]
    fake.insert_responses = [ForgeExecResult(rowcount=1, lastrowid=9)]
    svc = ModelUpdateService(sql=fake)
    result = svc.create_column(
        table_name="visits",
        column_name="visit_id",
        data_type="INT",
        description=None,
        is_active=True,
        created_by="user",
    )
    assert result["tableName"] == "visits"


def test_create_column_duplicate_raises():
    fake = FakeForgeQueryPort()
    fake.query_mappings_responses = [[{"id": 7, "name": "visits"}]]
    fake.insert_exceptions = [RuntimeError("dup")]
    svc = ModelUpdateService(sql=fake)
    with pytest.raises(ForgeError):
        svc.create_column(
            table_name="visits",
            column_name="visit_id",
            data_type="INT",
            description=None,
            is_active=True,
            created_by="user",
        )
