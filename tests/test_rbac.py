"""
tests/test_rbac.py

Tests for RBAC role resolution, caching, and decorators.
Run with: pytest tests/test_rbac.py -v
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from valkey.exceptions import ConnectionError as ValkeyConnectionError

from app.services.rbac_service import (
    assign_role,
    get_effective_roles,
    user_has_role,
    workspace_has_feature,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_no_cache():
    """Simulate empty cache — forces DB load path."""
    with patch("app.services.rbac_service._valkey") as mock:
        client = MagicMock()
        client.smembers.return_value = set()
        mock.return_value = client
        yield client


def _mock_user_roles(role_names: list[str]):
    """Helper: mock UserRole DB query to return given role names."""
    mock_roles = []
    for name in role_names:
        ur = MagicMock()
        ur.role = MagicMock()
        ur.role.name = name
        mock_roles.append(ur)
    return mock_roles


# ---------------------------------------------------------------------------
# Role resolution — basic
# ---------------------------------------------------------------------------


def test_user_with_no_roles_has_empty_effective_roles(mock_no_cache):
    with patch("app.services.rbac_service.get_user_roles", return_value=set()):
        roles = get_effective_roles(user_id=1)
    assert roles == set()


def test_user_with_explicit_role(mock_no_cache):
    with patch("app.services.rbac_service.get_user_roles", return_value={"forge_match:user"}):
        roles = get_effective_roles(user_id=1)
    assert "forge_match:user" in roles


# ---------------------------------------------------------------------------
# Role resolution — implied roles
# ---------------------------------------------------------------------------


def test_workspace_admin_implies_all_feature_user_roles(mock_no_cache):
    with patch("app.services.rbac_service.get_user_roles", return_value={"workspace_admin"}):
        roles = get_effective_roles(user_id=1, workspace_id="ws-1")

    from app.models.rbac import FEATURE_KEYS
    for fk in FEATURE_KEYS:
        assert f"{fk}:user" in roles, f"Expected {fk}:user implied by workspace_admin"


def test_workspace_admin_does_not_imply_feature_admin_roles(mock_no_cache):
    with patch("app.services.rbac_service.get_user_roles", return_value={"workspace_admin"}):
        roles = get_effective_roles(user_id=1, workspace_id="ws-1")

    assert "forge_match:admin" not in roles


def test_feature_admin_implies_feature_user(mock_no_cache):
    with patch("app.services.rbac_service.get_user_roles", return_value={"forge_match:admin"}):
        roles = get_effective_roles(user_id=1)

    assert "forge_match:user" in roles
    assert "forge_match:admin" in roles


def test_feature_admin_does_not_imply_other_feature_user(mock_no_cache):
    with patch("app.services.rbac_service.get_user_roles", return_value={"forge_match:admin"}):
        roles = get_effective_roles(user_id=1)

    assert "query_studio:user" not in roles
    assert "skills:user" not in roles


def test_super_admin_has_all_roles(mock_no_cache):
    with patch("app.services.rbac_service.get_user_roles", return_value={"super_admin"}):
        roles = get_effective_roles(user_id=1)

    from app.models.rbac import FEATURE_KEYS
    for fk in FEATURE_KEYS:
        assert f"{fk}:user" in roles
        assert f"{fk}:admin" in roles
    assert "workspace_admin" in roles


def test_assign_role_ensures_workspace_membership_for_workspace_scoped_roles(monkeypatch):
    import app.extensions as extensions
    import app.services.rbac_service as rbac_service

    role = MagicMock()
    role.id = 7
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    monkeypatch.setattr(rbac_service.Role, "get_by_name", lambda name: role)

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        rbac_service,
        "_ensure_workspace_membership_for_role",
        lambda **kwargs: captured.update(kwargs),
    )
    monkeypatch.setattr(rbac_service, "invalidate_user_roles", lambda *args, **kwargs: None)
    monkeypatch.setattr(extensions, "db", SimpleNamespace(session=session))

    assign_role(
        user_id="u-1",
        role_name="skills:user",
        granted_by="admin-1",
        workspace_id="ws-9",
    )

    assert captured == {
        "user_id": "u-1",
        "role_name": "skills:user",
        "workspace_id": "ws-9",
    }
    session.commit.assert_called_once()


def test_assign_role_ensures_workspace_membership_for_super_admin_when_context_workspace_present(monkeypatch):
    import app.extensions as extensions
    import app.services.rbac_service as rbac_service

    role = MagicMock()
    role.id = 1
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    monkeypatch.setattr(rbac_service.Role, "get_by_name", lambda name: role)

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        rbac_service,
        "_ensure_workspace_membership_for_role",
        lambda **kwargs: captured.update(kwargs),
    )
    monkeypatch.setattr(rbac_service, "invalidate_user_roles", lambda *args, **kwargs: None)
    monkeypatch.setattr(extensions, "db", SimpleNamespace(session=session))

    assign_role(
        user_id="u-1",
        role_name="super_admin",
        granted_by="admin-1",
        workspace_id="ws-9",
    )

    assert captured["workspace_id"] == "ws-9"
    session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# user_has_role
# ---------------------------------------------------------------------------


def test_user_has_role_true(mock_no_cache):
    with patch("app.services.rbac_service.get_user_roles", return_value={"skills:user"}):
        assert user_has_role(1, "skills:user") is True


def test_user_has_role_false(mock_no_cache):
    with patch("app.services.rbac_service.get_user_roles", return_value={"skills:user"}):
        assert user_has_role(1, "skills:admin") is False


def test_user_has_role_implied(mock_no_cache):
    with patch("app.services.rbac_service.get_user_roles", return_value={"skills:admin"}):
        assert user_has_role(1, "skills:user") is True


# ---------------------------------------------------------------------------
# workspace_has_feature
# ---------------------------------------------------------------------------


def test_workspace_has_active_feature(mock_no_cache):
    with patch("app.services.rbac_service.get_workspace_features", return_value={"forge_match", "skills"}):
        assert workspace_has_feature(workspace_id=1, feature_key="forge_match") is True


def test_workspace_missing_feature(mock_no_cache):
    with patch("app.services.rbac_service.get_workspace_features", return_value={"forge_match"}):
        assert workspace_has_feature(workspace_id=1, feature_key="skills") is False


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------


def test_require_role_passes_with_correct_role(app):
    from app.decorators.rbac import require_role
    with app.test_request_context("/"):
        from flask import g
        g.user_id = 1
        g.effective_roles = {"forge_match:user"}

        @require_role("forge_match:user")
        def view():
            return "ok"

        assert view() == "ok"


def test_require_role_fails_with_wrong_role(app):
    from app.decorators.rbac import require_role
    with app.test_request_context("/"):
        from flask import g
        g.user_id = 1
        g.effective_roles = {"skills:user"}

        @require_role("forge_match:user")
        def view():
            return "ok"

        with pytest.raises(Exception) as exc_info:
            view()
        assert "403" in str(exc_info.value) or "Forbidden" in str(exc_info.value)


def test_require_role_super_admin_bypasses(app):
    from app.decorators.rbac import require_role
    with app.test_request_context("/"):
        from flask import g
        g.user_id = 1
        g.effective_roles = {"super_admin", "forge_match:user", "forge_match:admin"}

        @require_role("forge_match:admin")
        def view():
            return "ok"

        assert view() == "ok"


def test_require_feature_bypassed_for_workspace_admin(app):
    from app.decorators.rbac import require_feature
    with app.test_request_context("/"):
        from flask import g
        g.user_id = 1
        g.workspace_id = 5
        g.effective_roles = {"workspace_admin", "forge_match:user"}

        @require_feature("skills")
        def view():
            return "ok"

        # workspace_admin bypasses feature check even if skills not in workspace
        assert view() == "ok"


def test_require_feature_fails_for_regular_user(app):
    from app.decorators.rbac import require_feature
    with app.test_request_context("/"):
        from flask import g
        g.user_id = 1
        g.workspace_id = 5
        g.effective_roles = {"forge_match:user"}

        with patch("app.decorators.rbac.workspace_has_feature", return_value=False):
            @require_feature("skills")
            def view():
                return "ok"

        with pytest.raises(Exception) as exc_info:
            view()
        assert "403" in str(exc_info.value) or "Forbidden" in str(exc_info.value)


def test_require_access_admin_bypassed_for_workspace_admin(app):
    from app.decorators.rbac import require_access
    with app.test_request_context("/"):
        from flask import g
        g.user_id = 1
        g.workspace_id = "ws-1"
        g.effective_roles = {"workspace_admin"}

        @require_access("ingestion", role="admin")
        def view():
            return "ok"

        assert view() == "ok"


def test_require_access_shortcut(app):
    from app.decorators.rbac import require_access
    with app.test_request_context("/"):
        from flask import g
        g.user_id = 1
        g.workspace_id = 5
        g.effective_roles = {"forge_match:user"}

        with patch("app.decorators.rbac.workspace_has_feature", return_value=True):
            @require_access("forge_match")
            def view():
                return "ok"

            assert view() == "ok"


# ---------------------------------------------------------------------------
# Cache invalidation
# ---------------------------------------------------------------------------


def test_invalidate_clears_user_cache():
    from app.services.rbac_service import invalidate_user_roles
    with patch("app.services.rbac_service._valkey") as mock:
        client = MagicMock()
        client.keys.return_value = ["qf:roles:user:42:ws-1", "qf:roles:user:42:__global__"]
        mock.return_value = client
        invalidate_user_roles(user_id=42)
        client.delete.assert_called_once_with("qf:roles:user:42:ws-1", "qf:roles:user:42:__global__")


def test_invalidate_clears_workspace_feature_cache():
    from app.services.rbac_service import invalidate_workspace_features
    with patch("app.services.rbac_service._valkey") as mock:
        client = MagicMock()
        mock.return_value = client
        invalidate_workspace_features(workspace_id=7)
        client.delete.assert_called_once_with("qf:features:workspace:7")


def test_get_user_roles_tolerates_valkey_cache_failure(monkeypatch):
    import app.services.rbac_service as rbac_service

    client = MagicMock()
    client.smembers.side_effect = ValkeyConnectionError("cache unavailable")
    monkeypatch.setattr(rbac_service, "_valkey", lambda: client)

    query = MagicMock()
    query.filter.return_value = query
    query.all.return_value = _mock_user_roles(["skills:user"])
    monkeypatch.setattr(rbac_service.UserRole, "query", MagicMock(join=MagicMock(return_value=query)))

    roles = rbac_service.get_user_roles(user_id="u-1", workspace_id="ws-1")

    assert roles == {"skills:user"}


def test_get_user_roles_does_not_swallow_non_cache_errors(monkeypatch):
    import app.services.rbac_service as rbac_service

    monkeypatch.setattr(rbac_service, "_valkey", lambda: (_ for _ in ()).throw(ValueError("bad cache config")))

    with pytest.raises(ValueError, match="bad cache config"):
        rbac_service.get_user_roles(user_id="u-1", workspace_id="ws-1")
