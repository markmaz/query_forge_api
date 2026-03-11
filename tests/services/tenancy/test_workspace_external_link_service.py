from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.tenancy.datasource_resolver_service import ResolvedWorkspaceDatasource
from app.services.tenancy.workspace_external_link_service import WorkspaceExternalLinkService


def test_list_links_databricks_from_workspace_host(monkeypatch):
    monkeypatch.setattr(
        "app.services.tenancy.workspace_external_link_service.WorkspaceDatasourceResolverService.resolve_for_workspace",
        lambda *_args, **_kwargs: ResolvedWorkspaceDatasource(
            workspace_id="ws-1",
            workspace_name="Main",
            organization_id="org-1",
            organization_is_active=True,
            workspace_is_active=True,
            datasource_id=1,
            datasource_name="DBX",
            datasource_slug="dbx",
            datasource_type="databricks",
            datasource_is_active=True,
            config_json={"host": "https://adb-1.azuredatabricks.net"},
            secret_ref=None,
            default_catalog=None,
            default_schema=None,
        ),
    )
    out = WorkspaceExternalLinkService().list_links(workspace_id="ws-1")
    assert out["datasource_type"] == "databricks"
    assert out["links"][0]["label"] == "Databricks"
    assert out["links"][0]["url"] == "https://adb-1.azuredatabricks.net"


def test_list_links_snowflake_from_account(monkeypatch):
    monkeypatch.setattr(
        "app.services.tenancy.workspace_external_link_service.WorkspaceDatasourceResolverService.resolve_for_workspace",
        lambda *_args, **_kwargs: ResolvedWorkspaceDatasource(
            workspace_id="ws-1",
            workspace_name="Main",
            organization_id="org-1",
            organization_is_active=True,
            workspace_is_active=True,
            datasource_id=2,
            datasource_name="SF",
            datasource_slug="sf",
            datasource_type="snowflake",
            datasource_is_active=True,
            config_json={"account": "xy12345"},
            secret_ref=None,
            default_catalog=None,
            default_schema=None,
        ),
    )
    out = WorkspaceExternalLinkService().list_links(workspace_id="ws-1")
    assert out["datasource_type"] == "snowflake"
    assert out["links"][0]["label"] == "Snowflake"
    assert out["links"][0]["url"] == "https://xy12345.snowflakecomputing.com"


def test_list_links_uses_explicit_external_url(monkeypatch):
    monkeypatch.setattr(
        "app.services.tenancy.workspace_external_link_service.WorkspaceDatasourceResolverService.resolve_for_workspace",
        lambda *_args, **_kwargs: ResolvedWorkspaceDatasource(
            workspace_id="ws-1",
            workspace_name="Main",
            organization_id="org-1",
            organization_is_active=True,
            workspace_is_active=True,
            datasource_id=3,
            datasource_name="Any",
            datasource_slug="any",
            datasource_type="mysql",
            datasource_is_active=True,
            config_json={"external_url": "https://portal.example.com"},
            secret_ref=None,
            default_catalog=None,
            default_schema=None,
        ),
    )
    out = WorkspaceExternalLinkService().list_links(workspace_id="ws-1")
    assert out["links"][0]["url"] == "https://portal.example.com"


def test_list_links_legacy_workspace_fallback(monkeypatch):
    monkeypatch.setattr(
        "app.services.tenancy.workspace_external_link_service.WorkspaceDatasourceResolverService.resolve_for_workspace",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.tenancy.workspace_external_link_service.WorkspaceService.get_workspace",
        lambda *_args, **_kwargs: {"server": "https://legacy-db.example.com"},
    )
    out = WorkspaceExternalLinkService().list_links(workspace_id="ws-1", allow_legacy_fallback=True)
    assert out["datasource_type"] == "databricks"
    assert out["links"][0]["url"] == "https://legacy-db.example.com"


def test_list_links_empty_when_no_binding_and_no_fallback(monkeypatch):
    monkeypatch.setattr(
        "app.services.tenancy.workspace_external_link_service.WorkspaceDatasourceResolverService.resolve_for_workspace",
        lambda *_args, **_kwargs: None,
    )
    out = WorkspaceExternalLinkService().list_links(workspace_id="ws-1", allow_legacy_fallback=False)
    assert out["links"] == []
    assert out["datasource_type"] is None


def test_list_links_requires_workspace_id():
    with pytest.raises(ForgeError) as exc:
        WorkspaceExternalLinkService().list_links(workspace_id="")
    assert exc.value.status_code == 400
