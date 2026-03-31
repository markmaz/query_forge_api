from __future__ import annotations

from app.services.domain.admin.domain_access_command_service import DomainAccessCommandService
from tests._support.fakes import FakeForgeQueryPort


def test_apply_changes_success(monkeypatch) -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [{"ok_domain": 1}],
        [{"user_id": "u1"}, {"user_id": "u2"}],
    ]
    sql.write_responses = [1]
    service = DomainAccessCommandService(sql=sql)
    monkeypatch.setattr(service, "_assert_can_edit_domain", lambda **_kwargs: None)

    res = service.apply_changes(
        workspace_id="ws1",
        editor_user_id="u1",
        domain_id=1,
        add=[{"user_id": "u1", "can_edit": True}],
        remove=["u2"],
    )
    assert res["added"] == 1
