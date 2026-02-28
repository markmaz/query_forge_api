from __future__ import annotations

from app.utils.jwt_claims import claim_has_role, claim_is_admin, get_roles_from_claim


def test_get_roles_from_claim_deduplicates_case_insensitive() -> None:
    payload = {"roles": ["Admin", "admin", "Viewer", "", None]}
    assert get_roles_from_claim(payload) == ["Admin", "Viewer"]


def test_claim_has_role() -> None:
    payload = {"roles": ["Editor", "Viewer"]}
    assert claim_has_role(payload, "viewer") is True
    assert claim_has_role(payload, "admin") is False


def test_claim_is_admin_from_roles_or_flag() -> None:
    assert claim_is_admin({"roles": ["Admin"]}) is True
    assert claim_is_admin({"is_admin": True}) is True
    assert claim_is_admin({"groups": ["admin"]}) is True
    assert claim_is_admin({"roles": ["Viewer"]}) is False

