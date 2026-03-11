from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.domain.domain_user_write_service import DomainUserWriteService
from tests._support.fakes import FakeForgeQueryPort


def test_norm_add_remove() -> None:
    assert DomainUserWriteService._norm_remove(["u1", "u1"]) == ["u1"]
    assert DomainUserWriteService._norm_add([{"user_id": "u1", "can_edit": "true"}]) == [("u1", True)]
    with pytest.raises(ForgeError):
        DomainUserWriteService._norm_add([{"user_id": ""}])


def test_upsert_user_success(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[{"ok_domain": 1, "ok_user": 1, "ok_workspace_member": 1}]]
    service = DomainUserWriteService(sql=sql)
    monkeypatch.setattr(service, "_assert_can_edit_domain", lambda **_kwargs: None)

    res = service.upsert_user(
        workspace_id="ws1",
        editor_user_id="u1",
        domain_id=1,
        tarrequire_user_id="u2",
        can_read=True,
        can_edit=False,
    )
    assert res["user_id"] == "u2"


def test_apply_changes_success(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"ok_domain": 1}],
        [{"user_id": "u1"}, {"user_id": "u2"}],
    ]
    sql.write_responses = [1]
    service = DomainUserWriteService(sql=sql)
    monkeypatch.setattr(service, "_assert_can_edit_domain", lambda **_kwargs: None)

    res = service.apply_changes(
        workspace_id="ws1",
        editor_user_id="u1",
        domain_id=1,
        add=[{"user_id": "u1", "can_edit": True}],
        remove=["u2"],
    )
    assert res["added"] == 1
