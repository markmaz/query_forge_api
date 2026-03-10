from __future__ import annotations

import io

import pytest
from werkzeug.datastructures import FileStorage

from app.exceptions.forge_error import ForgeError
from app.services.models.model_upload_service import ModelUploadService


class DummyWriter:
    def __init__(self) -> None:
        self.calls = []

    def upsert_dictionary(self, *, user_name: str, rows, full_replace: bool = False):
        self.calls.append({"user_name": user_name, "rows": rows, "full_replace": full_replace})
        return {
            "inserted_tables": 1,
            "inserted_columns": 2,
            "updated_columns": 0,
            "deactivated_columns": 0,
        }


def _file_storage(data: bytes, filename: str) -> FileStorage:
    return FileStorage(stream=io.BytesIO(data), filename=filename)


def test_upload_missing_file() -> None:
    svc = ModelUploadService(writer=DummyWriter())
    with pytest.raises(ForgeError):
        svc.upload(workspace_id="ws", user_id="u", file_storage=None)


def test_upload_missing_filename() -> None:
    svc = ModelUploadService(writer=DummyWriter())
    fs = _file_storage(b"data", "")
    with pytest.raises(ForgeError):
        svc.upload(workspace_id="ws", user_id="u", file_storage=fs)


def test_upload_empty_file() -> None:
    svc = ModelUploadService(writer=DummyWriter())
    fs = _file_storage(b"", "data.csv")
    with pytest.raises(ForgeError):
        svc.upload(workspace_id="ws", user_id="u", file_storage=fs)


def test_upload_unsupported_file_type() -> None:
    svc = ModelUploadService(writer=DummyWriter())
    fs = _file_storage(b"data", "data.txt")
    with pytest.raises(ForgeError):
        svc.upload(workspace_id="ws", user_id="u", file_storage=fs)


def test_upload_missing_columns() -> None:
    svc = ModelUploadService(writer=DummyWriter())
    fs = _file_storage(b"foo,bar\n1,2\n", "data.csv")
    result = svc.upload(workspace_id="ws", user_id="u", file_storage=fs)
    assert result["status"] == "FAILED"
    assert result["errors"]


def test_upload_success() -> None:
    writer = DummyWriter()
    svc = ModelUploadService(writer=writer)
    csv = b"table_name,column_name,data_type,description\npatients,id,INT,patient id\n"
    fs = _file_storage(csv, "data.csv")
    result = svc.upload(workspace_id="ws", user_id="u", file_storage=fs, full_replace=True, user_name="me")

    assert result["status"] == "SUCCESS"
    assert result["insertedTables"] == 1
    assert writer.calls[0]["user_name"] == "me"
