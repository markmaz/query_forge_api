from __future__ import annotations

import json
from datetime import datetime

import pytest

from app.exceptions.forge_error import ForgeError
from app.models.tenancy.tenancy_admin import (
    DatasourceCreateRequest,
    OrganizationCreateRequest,
    WorkspaceCreateRequest,
    WorkspaceBindingUpdateRequest,
    WorkspaceMembershipCreateRequest,
)
from app.services.tenancy.tenancy_admin_service import TenancyAdminService, _json_loads


def test_list_organizations_returns_paginated_rows():
    class _SQL:
        def execute_query_mappings(self, query, _params=None):
            if "COUNT(*) AS total" in query:
                return [{"total": 1}]
            return [
                {
                    "id": "org-1",
                    "name": "Acme",
                    "slug": "acme",
                    "description": None,
                    "is_active": 1,
                    "created_at": None,
                    "updated_at": None,
                }
            ]

    svc = TenancyAdminService(sql=_SQL())
    out = svc.list_organizations()
    assert out["count"] == 1
    assert out["rows"][0]["is_active"] is True


def test_create_organization_conflict_raises_409():
    class _SQL:
        def execute_query_mappings(self, query, _params=None):
            if "FROM organization" in query and "WHERE (id = :id OR slug = :slug)" in query:
                return [{"id": "org-1", "slug": "acme"}]
            return []

        def execute_write(self, *_args, **_kwargs):
            return 1

    svc = TenancyAdminService(sql=_SQL())
    with pytest.raises(ForgeError) as exc:
        svc.create_organization(OrganizationCreateRequest(name="Acme", slug="acme", id="org-1"))
    assert exc.value.status_code == 409


def test_get_organization_serializes_datetime_fields():
    now = datetime(2026, 3, 10, 14, 0, 0)

    class _SQL:
        def execute_query_mappings(self, query, _params=None):
            if "FROM organization" in query and "WHERE id = :id" in query:
                return [
                    {
                        "id": "org-1",
                        "name": "Acme",
                        "slug": "acme",
                        "description": None,
                        "is_active": 1,
                        "created_at": now,
                        "updated_at": now,
                    }
                ]
            return []

    svc = TenancyAdminService(sql=_SQL())
    row = svc.get_organization("org-1")
    assert row["created_at"] == now.isoformat()
    assert row["updated_at"] == now.isoformat()


def test_list_organization_memberships_includes_user_profile_fields():
    class _SQL:
        def execute_query_mappings(self, query, _params=None):
            if "FROM organization\n" in query and "WHERE id = :id" in query:
                return [
                    {
                        "id": "org-1",
                        "name": "Acme",
                        "slug": "acme",
                        "description": None,
                        "is_active": 1,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            if "COUNT(*) AS total" in query:
                return [{"total": 1}]
            if "FROM organization_membership om" in query:
                assert "LEFT JOIN users u ON u.user_id = om.user_id" in query
                return [
                    {
                        "id": 10,
                        "organization_id": "org-1",
                        "user_id": "user-1",
                        "role": "org_admin",
                        "is_active": 1,
                        "created_at": None,
                        "updated_at": None,
                        "username": "taylor",
                        "email": "taylor@example.com",
                        "first_name": "Taylor",
                        "last_name": "Jordan",
                        "display_name": "Taylor Jordan",
                    }
                ]
            return []

    svc = TenancyAdminService(sql=_SQL())
    out = svc.list_organization_memberships(organization_id="org-1")

    assert out["rows"][0]["user_id"] == "user-1"
    assert out["rows"][0]["email"] == "taylor@example.com"
    assert out["rows"][0]["first_name"] == "Taylor"
    assert out["rows"][0]["last_name"] == "Jordan"
    assert out["rows"][0]["display_name"] == "Taylor Jordan"


def test_list_workspace_memberships_includes_user_profile_fields():
    class _SQL:
        def execute_query_mappings(self, query, _params=None):
            if "FROM workspace WHERE id = :id" in query:
                return [{"id": "ws-1"}]
            if "COUNT(*) AS total" in query:
                return [{"total": 1}]
            if "FROM workspace_membership wm" in query:
                assert "LEFT JOIN users u ON u.user_id = wm.user_id" in query
                return [
                    {
                        "id": 11,
                        "workspace_id": "ws-1",
                        "user_id": "user-2",
                        "role": "admin",
                        "is_active": 1,
                        "is_default": 0,
                        "created_at": None,
                        "updated_at": None,
                        "username": "jamie",
                        "email": "jamie@example.com",
                        "first_name": "Jamie",
                        "last_name": "Rivera",
                        "display_name": "Jamie Rivera",
                    }
                ]
            return []

    svc = TenancyAdminService(sql=_SQL())
    out = svc.list_workspace_memberships(workspace_id="ws-1")

    assert out["rows"][0]["user_id"] == "user-2"
    assert out["rows"][0]["email"] == "jamie@example.com"
    assert out["rows"][0]["display_name"] == "Jamie Rivera"


def test_delete_datasource_soft_sets_inactive():
    class _SQL:
        def __init__(self):
            self.writes = []

        def execute_query_mappings(self, query, params=None):
            if "FROM datasource" in query and "WHERE id = :id" in query:
                return [
                    {
                        "id": 9,
                        "organization_id": "org-1",
                        "name": "primary",
                        "slug": "primary",
                        "type": "mysql",
                        "description": None,
                        "is_active": 1,
                        "secret_ref": None,
                        "config_json": {},
                        "last_tested_at": None,
                        "last_test_status": None,
                        "last_test_message": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            return []

        def execute_write(self, query, params=None):
            self.writes.append((query, params))
            return 1

    sql = _SQL()
    svc = TenancyAdminService(sql=sql)
    out = svc.delete_datasource(datasource_id=9, hard=False)
    assert out["deleted"] is True
    assert out["mode"] == "soft"
    assert any("SET is_active = 0" in q for q, _ in sql.writes)


def test_test_datasource_success_updates_status(monkeypatch):
    class _Executor:
        def test_connection(self):
            return None

    class _SQL:
        def __init__(self):
            self.last_params = None

        def execute_query_mappings(self, query, _params=None):
            if "FROM datasource" in query and "WHERE id = :id" in query:
                return [
                    {
                        "id": 4,
                        "organization_id": "org-1",
                        "name": "primary",
                        "slug": "primary",
                        "type": "mysql",
                        "description": None,
                        "is_active": 1,
                        "secret_ref": None,
                        "config_json": {"host": "h", "port": 3306, "database": "d", "user": "u", "password": "p"},
                        "last_tested_at": None,
                        "last_test_status": None,
                        "last_test_message": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            return []

        def execute_write(self, _query, params=None):
            self.last_params = dict(params or {})
            return 1

    monkeypatch.setattr("app.services.tenancy.tenancy_admin_service.ExecutorFactory.create", lambda *_args, **_kwargs: _Executor())
    sql = _SQL()
    svc = TenancyAdminService(sql=sql)
    out = svc.test_datasource(datasource_id=4)
    assert out["status"] == "ok"
    assert sql.last_params["last_test_status"] == "ok"


def test_list_datasource_namespaces_returns_catalogs_and_schemas(monkeypatch):
    class _Executor:
        def execute(self, sql):
            assert sql == "SHOW DATABASES"
            return [{"name": "ANALYTICS"}, {"name": "RAW"}]

    class _Provider:
        def list_schemas(self, catalog):
            assert catalog == "ANALYTICS"
            return ["PUBLIC", "REPORTING"]

    class _SQL:
        def execute_query_mappings(self, query, _params=None):
            if "FROM datasource" in query and "WHERE id = :id" in query:
                return [
                    {
                        "id": 4,
                        "organization_id": "org-1",
                        "name": "primary",
                        "slug": "primary",
                        "type": "snowflake",
                        "description": None,
                        "is_active": 1,
                        "secret_ref": None,
                        "config_json": {"account": "acct", "user": "svc", "database": "ANALYTICS", "password": "p"},
                        "last_tested_at": None,
                        "last_test_status": None,
                        "last_test_message": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            return []

    monkeypatch.setattr("app.services.tenancy.tenancy_admin_service.ExecutorFactory.create", lambda *_args, **_kwargs: _Executor())
    monkeypatch.setattr("app.services.tenancy.tenancy_admin_service.MetadataProviderFactory.create", lambda *_args, **_kwargs: _Provider())

    svc = TenancyAdminService(sql=_SQL())
    out = svc.list_datasource_namespaces(datasource_id=4)

    assert out["catalogs"] == ["ANALYTICS", "RAW"]
    assert out["schemas"] == ["PUBLIC", "REPORTING"]
    assert out["current_catalog"] == "ANALYTICS"
    assert out["current_schema"] == "PUBLIC"


def test_upsert_workspace_membership_missing_workspace_raises_404():
    class _SQL:
        def execute_query_mappings(self, query, _params=None):
            if "FROM workspace WHERE id = :id" in query:
                return []
            return []

        def execute_write(self, *_args, **_kwargs):
            return 1

    svc = TenancyAdminService(sql=_SQL())
    with pytest.raises(ForgeError) as exc:
        svc.upsert_workspace_membership(
            workspace_id="ws-404",
            req=WorkspaceMembershipCreateRequest(user_id="user-1"),
        )
    assert exc.value.status_code == 404


def test_create_datasource_requires_org():
    class _SQL:
        def execute_query_mappings(self, query, _params=None):
            if "FROM organization" in query and "WHERE id = :id" in query:
                return []
            return []

        def execute_insert(self, *_args, **_kwargs):
            raise AssertionError("should not insert when org is missing")

    svc = TenancyAdminService(sql=_SQL())
    with pytest.raises(ForgeError) as exc:
        svc.create_datasource(
            organization_id="org-missing",
            req=DatasourceCreateRequest(name="primary", type="snowflake"),
        )
    assert exc.value.status_code == 404


def test_create_datasource_encrypts_sensitive_config_and_masks_public_response(monkeypatch):
    class _InsertResult:
        lastrowid = 8

    class _SQL:
        def __init__(self):
            self.insert_params = None

        def execute_query_mappings(self, query, params=None):
            if "FROM organization" in query and "WHERE id = :id" in query:
                return [{"id": "org-1", "name": "Acme", "slug": "acme", "is_active": 1}]
            if "FROM datasource" in query and "organization_id = :organization_id" in query:
                return []
            if "FROM datasource" in query and "WHERE id = :id" in query:
                return [
                    {
                        "id": 8,
                        "organization_id": "org-1",
                        "name": "primary",
                        "slug": "primary",
                        "type": "snowflake",
                        "description": None,
                        "is_active": 1,
                        "secret_ref": None,
                        "config_json": self.insert_params["config_json"],
                        "last_tested_at": None,
                        "last_test_status": None,
                        "last_test_message": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            return []

        def execute_insert(self, _query, params=None):
            self.insert_params = dict(params or {})
            return _InsertResult()

    monkeypatch.setattr(
        "app.services.tenancy.datasource_config_crypto.encrypt_secret",
        lambda value: f"enc::{value}",
    )
    monkeypatch.setattr(
        "app.services.tenancy.datasource_config_crypto.decrypt_secret",
        lambda value: value.replace("enc::", "", 1),
    )

    sql = _SQL()
    svc = TenancyAdminService(sql=sql)
    out = svc.create_datasource(
        organization_id="org-1",
        req=DatasourceCreateRequest(
            name="primary",
            type="snowflake",
            config_json={"account": "acct", "user": "svc", "password": "secret-1"},
        ),
    )

    stored_config = json.loads(sql.insert_params["config_json"])
    assert "password" not in stored_config
    assert stored_config["password_encrypted"] == "enc::secret-1"
    assert out["config_json"]["password"] == "******"


def test_create_databricks_datasource_encrypts_oauth_credentials(monkeypatch):
    class _InsertResult:
        lastrowid = 18

    class _SQL:
        def __init__(self):
            self.insert_params = None

        def execute_query_mappings(self, query, params=None):
            if "FROM organization" in query and "WHERE id = :id" in query:
                return [{"id": "org-1", "name": "Acme", "slug": "acme", "is_active": 1}]
            if "FROM datasource" in query and "organization_id = :organization_id" in query:
                return []
            if "FROM datasource" in query and "WHERE id = :id" in query:
                return [
                    {
                        "id": 18,
                        "organization_id": "org-1",
                        "name": "dbx-oauth",
                        "slug": "dbx-oauth",
                        "type": "databricks",
                        "description": None,
                        "is_active": 1,
                        "secret_ref": None,
                        "config_json": self.insert_params["config_json"],
                        "last_tested_at": None,
                        "last_test_status": None,
                        "last_test_message": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            return []

        def execute_insert(self, _query, params=None):
            self.insert_params = dict(params or {})
            return _InsertResult()

    monkeypatch.setattr(
        "app.services.tenancy.datasource_config_crypto.encrypt_secret",
        lambda value: f"enc::{value}",
    )
    monkeypatch.setattr(
        "app.services.tenancy.datasource_config_crypto.decrypt_secret",
        lambda value: value.replace("enc::", "", 1),
    )

    sql = _SQL()
    svc = TenancyAdminService(sql=sql)
    out = svc.create_datasource(
        organization_id="org-1",
        req=DatasourceCreateRequest(
            name="dbx-oauth",
            type="databricks",
            config_json={
                "host": "https://adb-1.azuredatabricks.net",
                "http_path": "/sql/1.0/warehouses/w1",
                "auth_method": "oauth_client_credentials",
                "client_id": "client-1",
                "client_secret": "secret-1",
            },
        ),
    )

    stored_config = json.loads(sql.insert_params["config_json"])
    assert stored_config["client_id_encrypted"] == "enc::client-1"
    assert stored_config["client_secret_encrypted"] == "enc::secret-1"
    assert "client_id" not in stored_config
    assert "client_secret" not in stored_config
    assert out["config_json"]["client_id"] == "******"
    assert out["config_json"]["client_secret"] == "******"


def test_create_snowflake_datasource_encrypts_private_key_material(monkeypatch):
    class _InsertResult:
        lastrowid = 12

    class _SQL:
        def __init__(self):
            self.insert_params = None

        def execute_query_mappings(self, query, params=None):
            if "FROM organization" in query and "WHERE id = :id" in query:
                return [{"id": "org-1", "name": "Acme", "slug": "acme", "is_active": 1}]
            if "FROM datasource" in query and "organization_id = :organization_id" in query:
                return []
            if "FROM datasource" in query and "WHERE id = :id" in query:
                return [
                    {
                        "id": 12,
                        "organization_id": "org-1",
                        "name": "primary",
                        "slug": "primary",
                        "type": "snowflake",
                        "description": None,
                        "is_active": 1,
                        "secret_ref": None,
                        "config_json": self.insert_params["config_json"],
                        "last_tested_at": None,
                        "last_test_status": None,
                        "last_test_message": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            return []

        def execute_insert(self, _query, params=None):
            self.insert_params = dict(params or {})
            return _InsertResult()

    monkeypatch.setattr(
        "app.services.tenancy.datasource_config_crypto.encrypt_secret",
        lambda value: f"enc::{value}",
    )
    monkeypatch.setattr(
        "app.services.tenancy.datasource_config_crypto.decrypt_secret",
        lambda value: value.replace("enc::", "", 1),
    )

    sql = _SQL()
    svc = TenancyAdminService(sql=sql)
    out = svc.create_datasource(
        organization_id="org-1",
        req=DatasourceCreateRequest(
            name="primary",
            type="snowflake",
            config_json={
                "account": "acct",
                "user": "svc",
                "auth_method": "rsa_key",
                "private_key_pem": "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
                "private_key_passphrase": "pass-1",
            },
        ),
    )

    stored_config = json.loads(sql.insert_params["config_json"])
    assert "private_key_pem" not in stored_config
    assert "private_key_passphrase" not in stored_config
    assert stored_config["private_key_pem_encrypted"].startswith("enc::")
    assert stored_config["private_key_passphrase_encrypted"] == "enc::pass-1"
    assert out["config_json"]["private_key_pem"] == "******"
    assert out["config_json"]["private_key_passphrase"] == "******"


def test_update_datasource_preserves_existing_encrypted_config_when_not_replaced():
    existing_config = json.dumps({"account": "acct", "password_encrypted": "enc::secret-1"})

    class _SQL:
        def __init__(self):
            self.write_params = None

        def execute_query_mappings(self, query, params=None):
            if "FROM datasource" in query and "WHERE id = :id" in query:
                effective_name = self.write_params["name"] if self.write_params else "primary"
                return [
                    {
                        "id": 9,
                        "organization_id": "org-1",
                        "name": effective_name,
                        "slug": "primary",
                        "type": "snowflake",
                        "description": None,
                        "is_active": 1,
                        "secret_ref": None,
                        "config_json": existing_config,
                        "last_tested_at": None,
                        "last_test_status": None,
                        "last_test_message": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            if "FROM datasource" in query and "organization_id = :organization_id" in query:
                return []
            return []

        def execute_write(self, _query, params=None):
            self.write_params = dict(params or {})
            return 1

    sql = _SQL()
    svc = TenancyAdminService(sql=sql)
    out = svc.update_datasource(datasource_id=9, req=type("Req", (), {"name": "renamed", "slug": None, "type": None, "description": None, "is_active": None, "secret_ref": None, "config_json": None})())

    assert sql.write_params["config_json"] == existing_config
    assert out["name"] == "renamed"


def test_update_datasource_preserves_masked_snowflake_private_key(monkeypatch):
    existing_config = json.dumps(
        {
            "account": "acct",
            "auth_method": "rsa_key",
            "private_key_pem_encrypted": "enc::pem-1",
            "private_key_passphrase_encrypted": "enc::pass-1",
        }
    )

    class _SQL:
        def __init__(self):
            self.write_params = None

        def execute_query_mappings(self, query, params=None):
            if "FROM datasource" in query and "WHERE id = :id" in query:
                return [
                    {
                        "id": 15,
                        "organization_id": "org-1",
                        "name": "primary",
                        "slug": "primary",
                        "type": "snowflake",
                        "description": None,
                        "is_active": 1,
                        "secret_ref": None,
                        "config_json": self.write_params["config_json"] if self.write_params else existing_config,
                        "last_tested_at": None,
                        "last_test_status": None,
                        "last_test_message": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            if "FROM datasource" in query and "organization_id = :organization_id" in query:
                return []
            return []

        def execute_write(self, _query, params=None):
            self.write_params = dict(params or {})
            return 1

    monkeypatch.setattr(
        "app.services.tenancy.datasource_config_crypto.decrypt_secret",
        lambda value: value.replace("enc::", "", 1),
    )

    sql = _SQL()
    svc = TenancyAdminService(sql=sql)
    out = svc.update_datasource(
        datasource_id=15,
        req=type(
            "Req",
            (),
            {
                "name": None,
                "slug": None,
                "type": None,
                "description": None,
                "is_active": None,
                "secret_ref": None,
                "config_json": {
                    "account": "acct",
                    "auth_method": "rsa_key",
                    "private_key_pem": "******",
                    "private_key_passphrase": "******",
                },
            },
        )(),
    )

    stored = json.loads(sql.write_params["config_json"])
    assert stored["private_key_pem_encrypted"] == "enc::pem-1"
    assert stored["private_key_passphrase_encrypted"] == "enc::pass-1"
    assert out["config_json"]["private_key_pem"] == "******"


def test_list_workspace_bindings_returns_rows():
    class _SQL:
        def execute_query_mappings(self, query, _params=None):
            if "COUNT(*) AS total" in query and "FROM workspace w" in query:
                return [{"total": 1}]
            if "FROM workspace w" in query:
                return [
                    {
                        "workspace_id": "ws-1",
                        "workspace_name": "Main",
                        "workspace_description": None,
                        "workspace_is_active": 1,
                        "default_catalog": "main",
                        "default_schema": "public",
                        "organization_id": "org-1",
                        "organization_name": "Acme",
                        "organization_is_active": 1,
                        "datasource_id": 7,
                        "datasource_name": "Primary",
                        "datasource_slug": "primary",
                        "datasource_type": "mysql",
                        "datasource_is_active": 1,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            if "FROM organization" in query and "WHERE id = :id" in query:
                return [{"id": "org-1", "name": "Acme", "slug": "acme", "is_active": 1}]
            return []

    svc = TenancyAdminService(sql=_SQL())
    out = svc.list_workspace_bindings(organization_id="org-1")
    assert out["count"] == 1
    assert out["rows"][0]["workspace_id"] == "ws-1"
    assert out["rows"][0]["datasource_id"] == 7


def test_test_datasource_decrypts_encrypted_password_before_executor(monkeypatch):
    captured = {}

    class _Executor:
        def test_connection(self):
            return None

    class _SQL:
        def execute_query_mappings(self, query, _params=None):
            if "FROM datasource" in query and "WHERE id = :id" in query:
                return [
                    {
                        "id": 4,
                        "organization_id": "org-1",
                        "name": "primary",
                        "slug": "primary",
                        "type": "mysql",
                        "description": None,
                        "is_active": 1,
                        "secret_ref": None,
                        "config_json": {"host": "h", "port": 3306, "database": "d", "user": "u", "password_encrypted": "enc::secret-1"},
                        "last_tested_at": None,
                        "last_test_status": None,
                        "last_test_message": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            return []

        def execute_write(self, _query, params=None):
            return params

    monkeypatch.setattr(
        "app.services.tenancy.datasource_config_crypto.decrypt_secret",
        lambda value: value.replace("enc::", "", 1),
    )
    monkeypatch.setattr(
        "app.services.tenancy.tenancy_admin_service.ExecutorFactory.create",
        lambda ds_type, cfg: captured.update({"type": ds_type, "cfg": dict(cfg)}) or _Executor(),
    )

    svc = TenancyAdminService(sql=_SQL())
    out = svc.test_datasource(datasource_id=4)
    assert out["status"] == "ok"
    assert captured["type"] == "mysql"
    assert captured["cfg"]["password"] == "secret-1"


def test_update_workspace_binding_rejects_org_datasource_mismatch():
    class _SQL:
        def execute_query_mappings(self, query, params=None):
            if "FROM workspace w" in query and "WHERE w.id = :workspace_id" in query:
                return [
                    {
                        "workspace_id": "ws-1",
                        "workspace_name": "Main",
                        "workspace_description": None,
                        "workspace_is_active": 1,
                        "default_catalog": None,
                        "default_schema": None,
                        "organization_id": "org-1",
                        "organization_name": "Acme",
                        "organization_is_active": 1,
                        "datasource_id": 1,
                        "datasource_name": "Old DS",
                        "datasource_slug": "old-ds",
                        "datasource_type": "mysql",
                        "datasource_is_active": 1,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            if "FROM organization" in query and "WHERE id = :id" in query:
                return [{"id": params["id"], "name": "Org", "slug": "org", "is_active": 1}]
            if "FROM datasource" in query and "WHERE id = :id" in query:
                return [
                    {
                        "id": params["id"],
                        "organization_id": "org-2",
                        "name": "DS",
                        "slug": "ds",
                        "type": "mysql",
                        "description": None,
                        "is_active": 1,
                        "secret_ref": None,
                        "config_json": {},
                        "last_tested_at": None,
                        "last_test_status": None,
                        "last_test_message": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            return []

        def execute_write(self, *_args, **_kwargs):
            return 1

    svc = TenancyAdminService(sql=_SQL())
    with pytest.raises(ForgeError) as exc:
        svc.update_workspace_binding(
            workspace_id="ws-1",
            req=WorkspaceBindingUpdateRequest(organization_id="org-1", datasource_id=22),
        )
    assert exc.value.status_code == 400


def test_create_workspace_creates_without_datasource():
    class _SQL:
        def __init__(self):
            self.writes = []

        def execute_query_mappings(self, query, params=None):
            if "FROM organization" in query and "WHERE id = :id" in query:
                return [{"id": params["id"], "name": "Org", "slug": "org", "is_active": 1}]
            if "SELECT id FROM workspace WHERE id = :id LIMIT 1" in query:
                return []
            if "FROM workspace w" in query and "WHERE w.id = :workspace_id" in query:
                return [
                    {
                        "workspace_id": params["workspace_id"],
                        "workspace_name": "Acme Workspace",
                        "workspace_description": "Primary",
                        "workspace_is_active": 1,
                        "default_catalog": "main",
                        "default_schema": "public",
                        "organization_id": "org-1",
                        "organization_name": "Org",
                        "organization_is_active": 1,
                        "datasource_id": None,
                        "datasource_name": None,
                        "datasource_slug": None,
                        "datasource_type": None,
                        "datasource_is_active": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            return []

        def execute_write(self, query, params=None):
            self.writes.append((query, dict(params or {})))
            return 1

    sql = _SQL()
    svc = TenancyAdminService(sql=sql)
    out = svc.create_workspace(
        WorkspaceCreateRequest(
            workspace_id="ws-new-1",
            organization_id="org-1",
            name="Acme Workspace",
            description="Primary",
            default_catalog="main",
            default_schema="public",
        )
    )
    assert out["workspace_id"] == "ws-new-1"
    assert any("INSERT INTO workspace (id) VALUES (:id)" in q for q, _ in sql.writes)


def test_create_workspace_rejects_datasource_org_mismatch():
    class _SQL:
        def execute_query_mappings(self, query, params=None):
            if "FROM organization" in query and "WHERE id = :id" in query:
                return [{"id": params["id"], "name": "Org", "slug": "org", "is_active": 1}]
            if "FROM datasource" in query and "WHERE id = :id" in query:
                return [
                    {
                        "id": params["id"],
                        "organization_id": "org-2",
                        "name": "DS",
                        "slug": "ds",
                        "type": "mysql",
                        "description": None,
                        "is_active": 1,
                        "secret_ref": None,
                        "config_json": {},
                        "last_tested_at": None,
                        "last_test_status": None,
                        "last_test_message": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            return []

        def execute_write(self, *_args, **_kwargs):
            return 1

    svc = TenancyAdminService(sql=_SQL())
    with pytest.raises(ForgeError) as exc:
        svc.create_workspace(
            WorkspaceCreateRequest(
                workspace_id="ws-new-2",
                organization_id="org-1",
                datasource_id=44,
            )
        )
    assert exc.value.status_code == 400


def test_delete_workspace_soft_sets_inactive():
    class _SQL:
        def __init__(self):
            self.writes = []

        def execute_query_mappings(self, query, params=None):
            if "FROM workspace w" in query and "WHERE w.id = :workspace_id" in query:
                return [
                    {
                        "workspace_id": params["workspace_id"],
                        "workspace_name": "Acme Workspace",
                        "workspace_description": None,
                        "workspace_is_active": 1,
                        "default_catalog": None,
                        "default_schema": None,
                        "organization_id": "org-1",
                        "organization_name": "Org",
                        "organization_is_active": 1,
                        "datasource_id": None,
                        "datasource_name": None,
                        "datasource_slug": None,
                        "datasource_type": None,
                        "datasource_is_active": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            return []

        def execute_write(self, query, params=None):
            self.writes.append((query, dict(params or {})))
            return 1

    sql = _SQL()
    svc = TenancyAdminService(sql=sql)
    out = svc.delete_workspace(workspace_id="ws-1")
    assert out == {"workspace_id": "ws-1", "deleted": True, "mode": "soft"}
    assert ("UPDATE workspace SET is_active = 0 WHERE id = :id", {"id": "ws-1"}) in sql.writes


def test_delete_workspace_hard_removes_row():
    class _SQL:
        def __init__(self):
            self.writes = []

        def execute_query_mappings(self, query, params=None):
            if "FROM workspace w" in query and "WHERE w.id = :workspace_id" in query:
                return [
                    {
                        "workspace_id": params["workspace_id"],
                        "workspace_name": "Acme Workspace",
                        "workspace_description": None,
                        "workspace_is_active": 1,
                        "default_catalog": None,
                        "default_schema": None,
                        "organization_id": "org-1",
                        "organization_name": "Org",
                        "organization_is_active": 1,
                        "datasource_id": None,
                        "datasource_name": None,
                        "datasource_slug": None,
                        "datasource_type": None,
                        "datasource_is_active": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            return []

        def execute_write(self, query, params=None):
            self.writes.append((query, dict(params or {})))
            return 1

    sql = _SQL()
    svc = TenancyAdminService(sql=sql)
    out = svc.delete_workspace(workspace_id="ws-1", hard=True)
    assert out == {"workspace_id": "ws-1", "deleted": True, "mode": "hard"}
    assert ("DELETE FROM workspace WHERE id = :id", {"id": "ws-1"}) in sql.writes


def test_test_datasource_surfaces_unexpected_executor_errors(monkeypatch):
    class _Executor:
        def test_connection(self):
            raise TypeError("bad executor wiring")

    class _SQL:
        def execute_query_mappings(self, query, _params=None):
            if "FROM datasource" in query and "WHERE id = :id" in query:
                return [
                    {
                        "id": 4,
                        "organization_id": "org-1",
                        "name": "primary",
                        "slug": "primary",
                        "type": "mysql",
                        "description": None,
                        "is_active": 1,
                        "secret_ref": None,
                        "config_json": {"host": "h", "port": 3306, "database": "d", "user": "u", "password": "p"},
                        "last_tested_at": None,
                        "last_test_status": None,
                        "last_test_message": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            return []

        def execute_write(self, _query, params=None):
            return params

    monkeypatch.setattr("app.services.tenancy.tenancy_admin_service.ExecutorFactory.create", lambda *_args, **_kwargs: _Executor())

    svc = TenancyAdminService(sql=_SQL())
    with pytest.raises(TypeError, match="bad executor wiring"):
        svc.test_datasource(datasource_id=4)


def test_list_datasource_namespaces_catalog_falls_back_for_expected_errors(monkeypatch):
    class _Executor:
        def execute(self, sql):
            del sql
            raise RuntimeError("catalog lookup unavailable")

    class _Provider:
        def list_schemas(self, catalog):
            assert catalog == "ANALYTICS"
            return ["PUBLIC"]

    class _SQL:
        def execute_query_mappings(self, query, _params=None):
            if "FROM datasource" in query and "WHERE id = :id" in query:
                return [
                    {
                        "id": 4,
                        "organization_id": "org-1",
                        "name": "primary",
                        "slug": "primary",
                        "type": "snowflake",
                        "description": None,
                        "is_active": 1,
                        "secret_ref": None,
                        "config_json": {"account": "acct", "user": "svc", "database": "ANALYTICS", "schema": "PUBLIC", "password": "p"},
                        "last_tested_at": None,
                        "last_test_status": None,
                        "last_test_message": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            return []

    monkeypatch.setattr("app.services.tenancy.tenancy_admin_service.ExecutorFactory.create", lambda *_args, **_kwargs: _Executor())
    monkeypatch.setattr("app.services.tenancy.tenancy_admin_service.MetadataProviderFactory.create", lambda *_args, **_kwargs: _Provider())

    svc = TenancyAdminService(sql=_SQL())
    out = svc.list_datasource_namespaces(datasource_id=4)

    assert out["catalogs"] == ["ANALYTICS"]
    assert out["schemas"] == ["PUBLIC"]


def test_list_datasource_namespaces_surfaces_unexpected_catalog_errors(monkeypatch):
    class _Executor:
        def execute(self, sql):
            del sql
            raise TypeError("bad catalog executor")

    class _SQL:
        def execute_query_mappings(self, query, _params=None):
            if "FROM datasource" in query and "WHERE id = :id" in query:
                return [
                    {
                        "id": 4,
                        "organization_id": "org-1",
                        "name": "primary",
                        "slug": "primary",
                        "type": "snowflake",
                        "description": None,
                        "is_active": 1,
                        "secret_ref": None,
                        "config_json": {"account": "acct", "user": "svc", "database": "ANALYTICS", "schema": "PUBLIC", "password": "p"},
                        "last_tested_at": None,
                        "last_test_status": None,
                        "last_test_message": None,
                        "created_at": None,
                        "updated_at": None,
                    }
                ]
            return []

    monkeypatch.setattr("app.services.tenancy.tenancy_admin_service.ExecutorFactory.create", lambda *_args, **_kwargs: _Executor())

    svc = TenancyAdminService(sql=_SQL())
    with pytest.raises(TypeError, match="bad catalog executor"):
        svc.list_datasource_namespaces(datasource_id=4)


def test_json_loads_returns_original_string_for_invalid_json() -> None:
    assert _json_loads("{not-json}") == "{not-json}"
