from __future__ import annotations

import pytest

from app.services.value_overrides.list_upload_service import ListUploadService


class _DummyWriter:
    def __init__(self):
        self.calls = []

    def insert_rows(self, list_type, rows):
        self.calls.append((list_type, rows))
        return len(rows)


def test_norm_and_infer_type() -> None:
    svc = ListUploadService(_DummyWriter())
    assert svc._norm_col("Customer Service Line") == "customer_service_line"
    assert svc._infer_type({"zipcode", "subregion", "region"}) == "regions"
    with pytest.raises(ValueError):
        svc._infer_type({"unknown"})


def test_validate_row_regions() -> None:
    svc = ListUploadService(_DummyWriter())
    errs = svc._validate_row("regions", 2, {"zipcode": "abc", "subregion": "", "region": ""})
    assert any(e.code == "INVALID_ZIP" for e in errs)


def test_handle_upload_type_mismatch() -> None:
    svc = ListUploadService(_DummyWriter())
    csv_bytes = b"zipcode,subregion,region\n12345,Sub,Reg\n"
    res = svc.handle_upload(
        file_bytes=csv_bytes,
        filename="data.csv",
        list_name="ListA",
        user_name="user1",
        workspace_id="ws1",
        user_id="u1",
        expected_type="npiCategories",
    )
    assert res.status == "FAILED"
    assert res.errors


def test_handle_upload_success() -> None:
    writer = _DummyWriter()
    svc = ListUploadService(writer)
    csv_bytes = b"zipcode,subregion,region\n12345,Sub,Reg\n"
    res = svc.handle_upload(
        file_bytes=csv_bytes,
        filename="data.csv",
        list_name="ListA",
        user_name="user1",
        workspace_id="ws1",
        user_id="u1",
    )
    assert res.status == "SUCCESS"
    assert res.insertedCount == 1
