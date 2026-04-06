from __future__ import annotations

import pytest
from flask import g

from app.exceptions.forge_error import ForgeError
from app.services.tenancy.datasource_resolver_service import ResolvedWorkspaceDatasource
from app.services.workspace_inventory.workspace_context import WorkspaceSqlContextBuilder


class _DummyForgeTokenPort:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


class _DummyExecutor:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


def test_build_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.WorkspaceService.get_workspace",
        lambda *_args, **_kwargs: {"server": "https://dbx"},
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.WarehouseService.get_warehouse_by_name",
        lambda *_args, **_kwargs: {"warehouse_id": "wh-1"},
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.resolve_request_username",
        lambda: "user-1",
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.DatabricksWorkspaceTokenProvider",
        _DummyForgeTokenPort,
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.DatabricksForgeQueryPort",
        _DummyExecutor,
    )

    ctx = WorkspaceSqlContextBuilder().build("ws-1")
    assert ctx.workspace_url == "https://dbx"
    assert ctx.warehouse_id == "wh-1"
    assert ctx.user_name == "user-1"


def test_resolve_workspace_url_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.WorkspaceService.get_workspace",
        lambda *_args, **_kwargs: {"workspace_id": "ws-1"},
    )
    builder = WorkspaceSqlContextBuilder()
    with pytest.raises(ForgeError):
        builder._resolve_workspace_url("ws-1")


def test_resolve_workspace_url_object(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.WorkspaceService.get_workspace",
        lambda *_args, **_kwargs: type("Ws", (), {"server": "https://dbx"})(),
    )
    builder = WorkspaceSqlContextBuilder()
    assert builder._resolve_workspace_url("ws-1") == "https://dbx"


def test_resolve_default_warehouse_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.WorkspaceService.get_workspace",
        lambda *_args, **_kwargs: {"server": "https://dbx"},
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.WarehouseService.get_warehouse_by_name",
        lambda *_args, **_kwargs: {},
    )
    builder = WorkspaceSqlContextBuilder()
    with pytest.raises(ForgeError):
        builder._resolve_default_warehouse_id("ws-1")


def test_build_context_forbidden_workspace_in_request_context(app, monkeypatch: pytest.MonkeyPatch) -> None:
    def _deny_workspace_access(self, *, user_id: str, workspace_id: str) -> str:
        raise ForgeError("You do not have access to this workspace", status_code=403)

    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.WorkspaceAccessService.assert_workspace_access",
        _deny_workspace_access,
    )
    with app.test_request_context("/"):
        g.user_id = "user-1"
        with pytest.raises(ForgeError) as exc:
            WorkspaceSqlContextBuilder().build("ws-1")
    assert exc.value.status_code == 403


def test_build_context_uses_workspace_datasource_databricks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.resolve_request_username",
        lambda: "user-1",
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.WorkspaceDatasourceResolverService.resolve_for_workspace",
        lambda *_args, **_kwargs: ResolvedWorkspaceDatasource(
            workspace_id="ws-1",
            workspace_name="WS",
            organization_id="org-1",
            organization_is_active=True,
            workspace_is_active=True,
            datasource_id=10,
            datasource_name="DBX",
            datasource_slug="dbx",
            datasource_type="databricks",
            datasource_is_active=True,
            config_json={"host": "https://adb-1.azuredatabricks.net", "warehouse_id": "wh-1", "token": "tok-1"},
            secret_ref=None,
            default_catalog="main",
            default_schema="asset",
        ),
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.DatabricksForgeQueryPort",
        _DummyExecutor,
    )

    ctx = WorkspaceSqlContextBuilder().build("ws-1")
    assert ctx.workspace_url == "https://adb-1.azuredatabricks.net"
    assert ctx.warehouse_id == "wh-1"
    assert isinstance(ctx.sql_exec, _DummyExecutor)


def test_build_context_uses_workspace_datasource_databricks_oauth(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.resolve_request_username",
        lambda: "user-1",
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.WorkspaceDatasourceResolverService.resolve_for_workspace",
        lambda *_args, **_kwargs: ResolvedWorkspaceDatasource(
            workspace_id="ws-1",
            workspace_name="WS",
            organization_id="org-1",
            organization_is_active=True,
            workspace_is_active=True,
            datasource_id=10,
            datasource_name="DBX",
            datasource_slug="dbx",
            datasource_type="databricks",
            datasource_is_active=True,
            config_json={
                "host": "https://adb-1.azuredatabricks.net",
                "warehouse_id": "wh-1",
                "auth_method": "oauth_client_credentials",
                "client_id": "client-1",
                "client_secret": "secret-1",
            },
            secret_ref=None,
            default_catalog="main",
            default_schema="asset",
        ),
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.create_databricks_oauth_provider",
        lambda **kwargs: captured.update(kwargs) or _DummyForgeTokenPort(),
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.DatabricksForgeQueryPort",
        _DummyExecutor,
    )

    ctx = WorkspaceSqlContextBuilder().build("ws-1")
    assert ctx.workspace_url == "https://adb-1.azuredatabricks.net"
    assert ctx.warehouse_id == "wh-1"
    assert captured["workspace_host"] == "https://adb-1.azuredatabricks.net"
    assert captured["workspace_id"] == "ws-1"


def test_build_context_uses_workspace_datasource_non_databricks(monkeypatch: pytest.MonkeyPatch) -> None:
    class _DummyAnalyticsExecutor:
        def execute(self, _sql: str, _params=None):
            return []

        def test_connection(self):
            return None

        def get_dialect(self):
            return "snowflake"

    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.resolve_request_username",
        lambda: "user-1",
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.WorkspaceDatasourceResolverService.resolve_for_workspace",
        lambda *_args, **_kwargs: ResolvedWorkspaceDatasource(
            workspace_id="ws-1",
            workspace_name="WS",
            organization_id="org-1",
            organization_is_active=True,
            workspace_is_active=True,
            datasource_id=11,
            datasource_name="SF",
            datasource_slug="sf",
            datasource_type="snowflake",
            datasource_is_active=True,
            config_json={"account": "a", "user": "u", "database": "d", "password": "p"},
            secret_ref=None,
            default_catalog=None,
            default_schema=None,
        ),
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.ExecutorFactory.create",
        lambda *_args, **_kwargs: _DummyAnalyticsExecutor(),
    )

    ctx = WorkspaceSqlContextBuilder().build("ws-1")
    assert ctx.workspace_url == ""
    assert ctx.warehouse_id == ""


def test_build_context_rejects_unsupported_datasource_type(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.resolve_request_username",
        lambda: "user-1",
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.WorkspaceDatasourceResolverService.resolve_for_workspace",
        lambda *_args, **_kwargs: ResolvedWorkspaceDatasource(
            workspace_id="ws-1",
            workspace_name="WS",
            organization_id="org-1",
            organization_is_active=True,
            workspace_is_active=True,
            datasource_id=12,
            datasource_name="Other",
            datasource_slug="other",
            datasource_type="oracle",
            datasource_is_active=True,
            config_json={},
            secret_ref=None,
            default_catalog=None,
            default_schema=None,
        ),
    )
    with pytest.raises(ForgeError) as exc:
        WorkspaceSqlContextBuilder().build("ws-1")
    assert exc.value.status_code == 400


def test_build_context_injects_secret_for_mysql_datasource(monkeypatch: pytest.MonkeyPatch) -> None:
    class _DummyAnalyticsExecutor:
        def execute(self, _sql: str, _params=None):
            return []

        def test_connection(self):
            return None

        def get_dialect(self):
            return "mysql"

    captured = {}

    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.resolve_request_username",
        lambda: "user-1",
    )
    monkeypatch.setenv("QF_TEST_MYSQL_PASSWORD", "pw-123")
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.WorkspaceDatasourceResolverService.resolve_for_workspace",
        lambda *_args, **_kwargs: ResolvedWorkspaceDatasource(
            workspace_id="ws-1",
            workspace_name="WS",
            organization_id="org-1",
            organization_is_active=True,
            workspace_is_active=True,
            datasource_id=13,
            datasource_name="MySQL",
            datasource_slug="mysql",
            datasource_type="mysql",
            datasource_is_active=True,
            config_json={"host": "localhost", "port": 3306, "database": "qf", "user": "root"},
            secret_ref="env:QF_TEST_MYSQL_PASSWORD",
            default_catalog=None,
            default_schema=None,
        ),
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.ExecutorFactory.create",
        lambda ds_type, cfg: captured.update({"type": ds_type, "cfg": dict(cfg)}) or _DummyAnalyticsExecutor(),
    )

    ctx = WorkspaceSqlContextBuilder().build("ws-1")
    assert ctx.workspace_id == "ws-1"
    assert captured["type"] == "mysql"
    assert captured["cfg"]["password"] == "pw-123"


def test_build_context_falls_back_to_legacy_on_expected_datasource_resolution_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.resolve_request_username",
        lambda: "user-1",
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.WorkspaceDatasourceResolverService.resolve_for_workspace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("resolver unavailable")),
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.WorkspaceService.get_workspace",
        lambda *_args, **_kwargs: {"server": "https://dbx"},
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.WarehouseService.get_warehouse_by_name",
        lambda *_args, **_kwargs: {"warehouse_id": "wh-1"},
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.DatabricksWorkspaceTokenProvider",
        _DummyForgeTokenPort,
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.DatabricksForgeQueryPort",
        _DummyExecutor,
    )

    ctx = WorkspaceSqlContextBuilder().build("ws-1")

    assert ctx.workspace_url == "https://dbx"
    assert ctx.warehouse_id == "wh-1"


def test_build_context_surfaces_unexpected_datasource_resolution_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.resolve_request_username",
        lambda: "user-1",
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.WorkspaceDatasourceResolverService.resolve_for_workspace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("resolver bug")),
    )

    with pytest.raises(AssertionError, match="resolver bug"):
        WorkspaceSqlContextBuilder().build("ws-1")
