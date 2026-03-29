"""
tests/test_ownership.py

Tests for ownership and sharing access control.
Run with: pytest tests/test_ownership.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.ownership_service import (
    apply_ownership_filter,
    can_modify_object,
    can_read_object,
    can_share_object,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_roles(roles: set[str]):
    return patch(
        "app.services.ownership_service._has_admin_access",
        return_value=any(r in roles for r in ("query_studio:admin", "skills:admin", "workspace_admin", "super_admin")),
    )


def _mock_admin(is_admin: bool):
    return patch("app.services.ownership_service._has_admin_access", return_value=is_admin)


# ---------------------------------------------------------------------------
# can_read_object
# ---------------------------------------------------------------------------


def test_owner_can_read():
    with _mock_admin(False):
        assert can_read_object(42, False, 42, "skills:admin", 1) is True


def test_shared_object_readable_by_non_owner():
    with _mock_admin(False):
        assert can_read_object(42, True, 99, "skills:admin", 1) is True


def test_unshared_non_owner_cannot_read():
    with _mock_admin(False):
        assert can_read_object(42, False, 99, "skills:admin", 1) is False


def test_admin_can_read_unshared_object():
    with _mock_admin(True):
        assert can_read_object(42, False, 99, "skills:admin", 1) is True


def test_null_owner_shared_object_readable_by_anyone():
    with _mock_admin(False):
        assert can_read_object(None, True, 99, "skills:admin", 1) is True


def test_null_owner_unshared_requires_admin():
    with _mock_admin(False):
        assert can_read_object(None, False, 99, "skills:admin", 1) is False


# ---------------------------------------------------------------------------
# can_modify_object — sharing does NOT grant write access
# ---------------------------------------------------------------------------


def test_owner_can_modify():
    with _mock_admin(False):
        assert can_modify_object(42, 42, "skills:admin", 1) is True


def test_non_owner_cannot_modify_even_if_shared():
    """Sharing grants read only — write still requires ownership or admin."""
    with _mock_admin(False):
        assert can_modify_object(42, 99, "skills:admin", 1) is False


def test_admin_can_modify_any_object():
    with _mock_admin(True):
        assert can_modify_object(42, 99, "skills:admin", 1) is True


def test_null_owner_non_admin_cannot_modify():
    with _mock_admin(False):
        assert can_modify_object(None, 99, "skills:admin", 1) is False


def test_null_owner_admin_can_modify():
    with _mock_admin(True):
        assert can_modify_object(None, 99, "skills:admin", 1) is True


# ---------------------------------------------------------------------------
# can_share_object (same rules as modify)
# ---------------------------------------------------------------------------


def test_owner_can_share():
    with _mock_admin(False):
        assert can_share_object(42, 42, "skills:admin", 1) is True


def test_non_owner_cannot_share():
    with _mock_admin(False):
        assert can_share_object(42, 99, "skills:admin", 1) is False


def test_admin_can_share_any_object():
    with _mock_admin(True):
        assert can_share_object(42, 99, "skills:admin", 1) is True


# ---------------------------------------------------------------------------
# apply_ownership_filter
# ---------------------------------------------------------------------------


def test_filter_non_admin_sees_own_and_shared(app):
    with app.app_context():
        with patch("app.services.ownership_service._has_admin_access", return_value=False):
            mock_query = MagicMock()
            mock_model = MagicMock()
            mock_model.created_by = MagicMock()
            mock_model.is_shared = MagicMock()

            apply_ownership_filter(mock_query, mock_model, 42, "skills:admin", 1)
            mock_query.filter.assert_called_once()


def test_filter_admin_sees_all(app):
    with app.app_context():
        with patch("app.services.ownership_service._has_admin_access", return_value=True):
            mock_query = MagicMock()
            mock_model = MagicMock()

            result = apply_ownership_filter(mock_query, mock_model, 99, "skills:admin", 1)
            # Admin path returns query unchanged — no filter applied
            mock_query.filter.assert_not_called()
            assert result is mock_query


# ---------------------------------------------------------------------------
# @require_ownership decorator
# ---------------------------------------------------------------------------


def test_decorator_owner_can_access(app):
    from app.decorators.ownership import require_ownership
    with app.test_request_context("/", method="PUT"):
        from flask import g
        g.user_id = 42
        g.workspace_id = 1
        g.effective_roles = {"query_studio:user"}

        mock_obj = MagicMock()
        mock_obj.created_by = 42
        mock_obj.is_shared = False

        with patch("app.decorators.ownership._load_model", return_value=mock_obj), \
             patch("app.services.ownership_service._has_admin_access", return_value=False):
            @require_ownership("SavedQuery", "query_id", "query_studio:admin")
            def view(query_id):
                return "ok"
            assert view(query_id=1) == "ok"
        assert g.owned_object is mock_obj


def test_decorator_non_owner_blocked_on_write(app):
    from app.decorators.ownership import require_ownership
    with app.test_request_context("/", method="DELETE"):
        from flask import g
        g.user_id = 99
        g.workspace_id = 1
        g.effective_roles = {"query_studio:user"}

        mock_obj = MagicMock()
        mock_obj.created_by = 42
        mock_obj.is_shared = True  # shared but still can't write

        with patch("app.decorators.ownership._load_model", return_value=mock_obj), \
             patch("app.services.ownership_service._has_admin_access", return_value=False):
            @require_ownership("SavedQuery", "query_id", "query_studio:admin")
            def view(query_id):
                return "ok"
            with pytest.raises(Exception) as exc:
                view(query_id=1)
            assert "403" in str(exc.value) or "permission" in str(exc.value).lower()


def test_decorator_shared_object_readable_by_non_owner(app):
    from app.decorators.ownership import require_ownership
    with app.test_request_context("/", method="GET"):
        from flask import g
        g.user_id = 99
        g.workspace_id = 1
        g.effective_roles = {"query_studio:user"}

        mock_obj = MagicMock()
        mock_obj.created_by = 42
        mock_obj.is_shared = True  # shared — readable by workspace

        with patch("app.decorators.ownership._load_model", return_value=mock_obj):
            @require_ownership("SavedQuery", "query_id", "query_studio:admin")
            def view(query_id):
                return "ok"
            assert view(query_id=1) == "ok"


def test_decorator_unshared_private_object_blocks_non_owner_read(app):
    from app.decorators.ownership import require_ownership
    with app.test_request_context("/", method="GET"):
        from flask import g
        g.user_id = 99
        g.workspace_id = 1
        g.effective_roles = {"skills:user"}

        mock_obj = MagicMock()
        mock_obj.created_by = 42
        mock_obj.is_shared = False  # not shared

        with patch("app.decorators.ownership._load_model", return_value=mock_obj), \
             patch("app.services.ownership_service._has_admin_access", return_value=False):
            @require_ownership("QuerySkill", "skill_id", "skills:admin", check_read=True)
            def view(skill_id):
                return "ok"
            with pytest.raises(Exception) as exc:
                view(skill_id=1)
            assert "403" in str(exc.value) or "permission" in str(exc.value).lower()


def test_decorator_shared_skill_readable_by_non_owner(app):
    from app.decorators.ownership import require_ownership
    with app.test_request_context("/", method="GET"):
        from flask import g
        g.user_id = 99
        g.workspace_id = 1
        g.effective_roles = {"skills:user"}

        mock_obj = MagicMock()
        mock_obj.created_by = 42
        mock_obj.is_shared = True  # shared skill — readable

        with patch("app.decorators.ownership._load_model", return_value=mock_obj), \
             patch("app.services.ownership_service._has_admin_access", return_value=False):
            @require_ownership("QuerySkill", "skill_id", "skills:admin", check_read=True)
            def view(skill_id):
                return "ok"
            assert view(skill_id=1) == "ok"


def test_decorator_super_admin_bypasses_all(app):
    from app.decorators.ownership import require_ownership
    with app.test_request_context("/", method="DELETE"):
        from flask import g
        g.user_id = 99
        g.workspace_id = 1
        g.effective_roles = {"super_admin"}

        mock_obj = MagicMock()
        mock_obj.created_by = 42
        mock_obj.is_shared = False

        with patch("app.decorators.ownership._load_model", return_value=mock_obj):
            @require_ownership("SavedQuery", "query_id", "query_studio:admin")
            def view(query_id):
                return "ok"
            assert view(query_id=1) == "ok"


def test_decorator_404_when_not_found(app):
    from app.decorators.ownership import require_ownership
    with app.test_request_context("/", method="GET"):
        from flask import g
        g.user_id = 42
        g.workspace_id = 1
        g.effective_roles = {"skills:user"}

        with patch("app.decorators.ownership._load_model", return_value=None):
            @require_ownership("QuerySkill", "skill_id", "skills:admin")
            def view(skill_id):
                return "ok"
            with pytest.raises(Exception) as exc:
                view(skill_id=999)
            assert "404" in str(exc.value)
