from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.tenancy.datasource_resolver_service import WorkspaceDatasourceResolverService


class _StubSQL:
    def __init__(self, rows):
        self._rows = rows

    def execute_query_mappings(self, _query: str, _params):
        return list(self._rows)


def test_resolve_workspace_datasource_success():
    service = WorkspaceDatasourceResolverService(
        sql=_StubSQL(
            [
                {
                    "workspace_id": "ws-1",
                    "workspace_name": "Main",
                    "workspace_organization_id": "org-1",
                    "organization_is_active": 1,
                    "workspace_is_active": 1,
                    "datasource_id": 10,
                    "default_catalog": "analytics",
                    "default_schema": "public",
                    "datasource_organization_id": "org-1",
                    "datasource_name": "Primary Snowflake",
                    "datasource_slug": "primary-sf",
                    "datasource_type": "snowflake",
                    "datasource_is_active": 1,
                    "config_json": {"account": "acct"},
                    "secret_ref": "env:SNOWFLAKE_PASSWORD",
                }
            ]
        )
    )

    resolved = service.resolve_for_workspace(workspace_id="ws-1")
    assert resolved is not None
    assert resolved.datasource_id == 10
    assert resolved.datasource_type == "snowflake"
    assert resolved.organization_id == "org-1"


def test_resolve_workspace_datasource_none_when_unbound():
    service = WorkspaceDatasourceResolverService(
        sql=_StubSQL(
            [
                {
                    "workspace_id": "ws-1",
                    "workspace_name": "Main",
                    "workspace_organization_id": "org-1",
                    "organization_is_active": 1,
                    "workspace_is_active": 1,
                    "datasource_id": None,
                    "default_catalog": None,
                    "default_schema": None,
                    "datasource_organization_id": None,
                    "datasource_name": None,
                    "datasource_slug": None,
                    "datasource_type": None,
                    "datasource_is_active": None,
                    "config_json": None,
                    "secret_ref": None,
                }
            ]
        )
    )
    assert service.resolve_for_workspace(workspace_id="ws-1") is None


def test_resolve_workspace_datasource_not_found():
    service = WorkspaceDatasourceResolverService(sql=_StubSQL([]))
    with pytest.raises(ForgeError) as exc:
        service.resolve_for_workspace(workspace_id="ws-404")
    assert exc.value.status_code == 404


def test_resolve_workspace_datasource_rejects_inactive_workspace():
    service = WorkspaceDatasourceResolverService(
        sql=_StubSQL(
            [
                {
                    "workspace_id": "ws-1",
                    "workspace_name": "Main",
                    "workspace_organization_id": "org-1",
                    "organization_is_active": 1,
                    "workspace_is_active": 0,
                    "datasource_id": 10,
                    "default_catalog": None,
                    "default_schema": None,
                    "datasource_organization_id": "org-1",
                    "datasource_name": "Primary",
                    "datasource_slug": "primary",
                    "datasource_type": "snowflake",
                    "datasource_is_active": 1,
                    "config_json": {},
                    "secret_ref": None,
                }
            ]
        )
    )
    with pytest.raises(ForgeError) as exc:
        service.resolve_for_workspace(workspace_id="ws-1")
    assert exc.value.status_code == 403


def test_resolve_workspace_datasource_rejects_inactive_datasource():
    service = WorkspaceDatasourceResolverService(
        sql=_StubSQL(
            [
                {
                    "workspace_id": "ws-1",
                    "workspace_name": "Main",
                    "workspace_organization_id": "org-1",
                    "organization_is_active": 1,
                    "workspace_is_active": 1,
                    "datasource_id": 10,
                    "default_catalog": None,
                    "default_schema": None,
                    "datasource_organization_id": "org-1",
                    "datasource_name": "Primary",
                    "datasource_slug": "primary",
                    "datasource_type": "snowflake",
                    "datasource_is_active": 0,
                    "config_json": {},
                    "secret_ref": None,
                }
            ]
        )
    )
    with pytest.raises(ForgeError) as exc:
        service.resolve_for_workspace(workspace_id="ws-1")
    assert exc.value.status_code == 403


def test_resolve_workspace_datasource_rejects_org_mismatch():
    service = WorkspaceDatasourceResolverService(
        sql=_StubSQL(
            [
                {
                    "workspace_id": "ws-1",
                    "workspace_name": "Main",
                    "workspace_organization_id": "org-1",
                    "organization_is_active": 1,
                    "workspace_is_active": 1,
                    "datasource_id": 10,
                    "default_catalog": None,
                    "default_schema": None,
                    "datasource_organization_id": "org-2",
                    "datasource_name": "Primary",
                    "datasource_slug": "primary",
                    "datasource_type": "snowflake",
                    "datasource_is_active": 1,
                    "config_json": {},
                    "secret_ref": None,
                }
            ]
        )
    )
    with pytest.raises(ForgeError) as exc:
        service.resolve_for_workspace(workspace_id="ws-1")
    assert exc.value.status_code == 500


def test_resolve_workspace_datasource_rejects_inactive_organization():
    service = WorkspaceDatasourceResolverService(
        sql=_StubSQL(
            [
                {
                    "workspace_id": "ws-1",
                    "workspace_name": "Main",
                    "workspace_organization_id": "org-1",
                    "organization_is_active": 0,
                    "workspace_is_active": 1,
                    "datasource_id": 10,
                    "default_catalog": None,
                    "default_schema": None,
                    "datasource_organization_id": "org-1",
                    "datasource_name": "Primary",
                    "datasource_slug": "primary",
                    "datasource_type": "snowflake",
                    "datasource_is_active": 1,
                    "config_json": {},
                    "secret_ref": None,
                }
            ]
        )
    )
    with pytest.raises(ForgeError) as exc:
        service.resolve_for_workspace(workspace_id="ws-1")
    assert exc.value.status_code == 403


def test_resolve_workspace_datasource_decrypts_sensitive_config(monkeypatch):
    monkeypatch.setattr(
        "app.services.tenancy.datasource_config_crypto.decrypt_secret",
        lambda value: value.replace("enc::", "", 1),
    )

    service = WorkspaceDatasourceResolverService(
        sql=_StubSQL(
            [
                {
                    "workspace_id": "ws-1",
                    "workspace_name": "Main",
                    "workspace_organization_id": "org-1",
                    "organization_is_active": 1,
                    "workspace_is_active": 1,
                    "datasource_id": 10,
                    "default_catalog": None,
                    "default_schema": None,
                    "datasource_organization_id": "org-1",
                    "datasource_name": "Primary",
                    "datasource_slug": "primary",
                    "datasource_type": "snowflake",
                    "datasource_is_active": 1,
                    "config_json": {"account": "acct", "password_encrypted": "enc::secret-1"},
                    "secret_ref": None,
                }
            ]
        )
    )

    resolved = service.resolve_for_workspace(workspace_id="ws-1")
    assert resolved is not None
    assert resolved.config_json["password"] == "secret-1"


def test_resolve_workspace_datasource_decrypts_private_key_material(monkeypatch):
    monkeypatch.setattr(
        "app.services.tenancy.datasource_config_crypto.decrypt_secret",
        lambda value: value.replace("enc::", "", 1),
    )

    service = WorkspaceDatasourceResolverService(
        sql=_StubSQL(
            [
                {
                    "workspace_id": "ws-1",
                    "workspace_name": "Main",
                    "workspace_organization_id": "org-1",
                    "organization_is_active": 1,
                    "workspace_is_active": 1,
                    "datasource_id": 10,
                    "default_catalog": None,
                    "default_schema": None,
                    "datasource_organization_id": "org-1",
                    "datasource_name": "Primary",
                    "datasource_slug": "primary",
                    "datasource_type": "snowflake",
                    "datasource_is_active": 1,
                    "config_json": {
                        "account": "acct",
                        "private_key_pem_encrypted": "enc::pem-body",
                        "private_key_passphrase_encrypted": "enc::pass-1",
                    },
                    "secret_ref": None,
                }
            ]
        )
    )

    resolved = service.resolve_for_workspace(workspace_id="ws-1")
    assert resolved is not None
    assert resolved.config_json["private_key_pem"] == "pem-body"
    assert resolved.config_json["private_key_passphrase"] == "pass-1"
