from __future__ import annotations

import pytest

from app.exceptions.service_error import ServiceError
from app.services.crosswalks import crosswalk_meta_writer
from app.services.crosswalks.crosswalk_meta_writer import CrosswalkMetaWriter
from tests._support.fakes import FakeSQLExecutor


def test_upsert_meta_inserts_uuid_and_params(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSQLExecutor()
    writer = CrosswalkMetaWriter(fake)

    monkeypatch.setattr(crosswalk_meta_writer, "uuid4", lambda: "uuid-1")

    writer.upsert_meta(
        workspace_id="ws1",
        list_type="regions",
        list_id="list-1",
        list_name="My List",
        user_id="user-1",
        user_name="Alice",
        is_shared=True,
    )

    assert len(fake.query_mappings_calls) == 1
    assert len(fake.write_calls) == 1
    call = fake.write_calls[0]
    assert "INSERT INTO crosswalk_list_meta" in call.query
    assert call.params["id"] == "uuid-1"
    assert call.params["is_shared"] == 1
    assert call.params["list_name"] == "My List"


def test_set_shared_reuses_table_check(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeSQLExecutor()
    writer = CrosswalkMetaWriter(fake)

    ids = iter(["uuid-2", "uuid-3"])
    monkeypatch.setattr(crosswalk_meta_writer, "uuid4", lambda: next(ids))

    writer.set_shared(workspace_id="ws1", list_type="regions", list_id="list-1", is_shared=False)
    writer.set_shared(workspace_id="ws1", list_type="regions", list_id="list-1", is_shared=True)

    assert len(fake.query_mappings_calls) == 1
    assert len(fake.write_calls) == 2
    assert fake.write_calls[0].params["id"] == "uuid-2"
    assert fake.write_calls[0].params["list_name"] == ""
    assert fake.write_calls[0].params["is_shared"] == 0
    assert fake.write_calls[1].params["id"] == "uuid-3"
    assert fake.write_calls[1].params["is_shared"] == 1


def test_delete_meta_executes_delete() -> None:
    fake = FakeSQLExecutor()
    writer = CrosswalkMetaWriter(fake)

    writer.delete_meta(workspace_id="ws1", list_type="regions", list_id="list-1")

    assert len(fake.query_mappings_calls) == 1
    assert len(fake.write_calls) == 1
    call = fake.write_calls[0]
    assert "DELETE FROM crosswalk_list_meta" in call.query
    assert call.params == {
        "workspace_id": "ws1",
        "list_type": "regions",
        "list_id": "list-1",
    }


def test_missing_table_raises_service_error() -> None:
    fake = FakeSQLExecutor()
    fake.query_mappings_exceptions.append(RuntimeError("missing"))
    writer = CrosswalkMetaWriter(fake)

    with pytest.raises(ServiceError, match="crosswalk_list_meta missing"):
        writer.upsert_meta(
            workspace_id="ws1",
            list_type="regions",
            list_id="list-1",
            list_name="My List",
            user_id=None,
            user_name=None,
            is_shared=False,
        )
