from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.value_overrides import value_override_meta_writer
from app.services.value_overrides.value_override_meta_writer import ValueOverrideMetaWriter
from tests._support.fakes import FakeForgeQueryPort


def test_upsert_meta_inserts_uuid_and_params(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeForgeQueryPort()
    writer = ValueOverrideMetaWriter(fake)

    monkeypatch.setattr(value_override_meta_writer, "uuid4", lambda: "uuid-1")

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


def test_set_shared_updates_existing_row() -> None:
    fake = FakeForgeQueryPort()
    fake.write_responses = [1, 1]
    writer = ValueOverrideMetaWriter(fake)

    writer.set_shared(workspace_id="ws1", list_type="regions", list_id="list-1", is_shared=False)
    writer.set_shared(workspace_id="ws1", list_type="regions", list_id="list-1", is_shared=True)

    assert len(fake.query_mappings_calls) == 1
    assert len(fake.write_calls) == 2
    assert "UPDATE crosswalk_list_meta" in fake.write_calls[0].query
    assert fake.write_calls[0].params["is_shared"] == 0
    assert fake.write_calls[1].params["is_shared"] == 1


def test_set_shared_raises_if_list_missing() -> None:
    fake = FakeForgeQueryPort()
    fake.write_responses = [0]
    writer = ValueOverrideMetaWriter(fake)

    with pytest.raises(ForgeError, match="List not found"):
        writer.set_shared(workspace_id="ws1", list_type="regions", list_id="missing", is_shared=True)


def test_delete_meta_executes_delete() -> None:
    fake = FakeForgeQueryPort()
    writer = ValueOverrideMetaWriter(fake)

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
    fake = FakeForgeQueryPort()
    fake.query_mappings_exceptions.append(RuntimeError("missing"))
    writer = ValueOverrideMetaWriter(fake)

    with pytest.raises(ForgeError, match="crosswalk_list_meta missing"):
        writer.upsert_meta(
            workspace_id="ws1",
            list_type="regions",
            list_id="list-1",
            list_name="My List",
            user_id=None,
            user_name=None,
            is_shared=False,
        )
