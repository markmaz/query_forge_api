from __future__ import annotations

import pytest

from app.exceptions.service_error import ServiceError
from app.services.workspace_inventory.workspace_context import WorkspaceContextBuilder


class _DummyTokenManager:
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
        "app.services.workspace_inventory.workspace_context.get_current_username",
        lambda: "user-1",
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.DatabricksWorkspaceTokenManager",
        _DummyTokenManager,
    )
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.DatabricksSQLExecutor",
        _DummyExecutor,
    )

    ctx = WorkspaceContextBuilder().build("ws-1")
    assert ctx.workspace_url == "https://dbx"
    assert ctx.warehouse_id == "wh-1"
    assert ctx.user_name == "user-1"


def test_resolve_workspace_url_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.WorkspaceService.get_workspace",
        lambda *_args, **_kwargs: {"workspace_id": "ws-1"},
    )
    builder = WorkspaceContextBuilder()
    with pytest.raises(ServiceError):
        builder._resolve_workspace_url("ws-1")


def test_resolve_workspace_url_object(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.workspace_inventory.workspace_context.WorkspaceService.get_workspace",
        lambda *_args, **_kwargs: type("Ws", (), {"server": "https://dbx"})(),
    )
    builder = WorkspaceContextBuilder()
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
    builder = WorkspaceContextBuilder()
    with pytest.raises(ServiceError):
        builder._resolve_default_warehouse_id("ws-1")
