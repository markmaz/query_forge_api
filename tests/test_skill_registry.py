from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

import app.skills.registry as registry_module
from app.skills.registry import SkillRegistry


def test_skill_registry_autodiscover_ignores_expected_submodule_import_errors() -> None:
    fake_package = SimpleNamespace(__path__=["/fake/skills"])

    def _import_module(name: str):
        if name == "app.skills":
            return fake_package
        if name == "app.skills.example":
            raise ImportError("missing optional dependency")
        raise AssertionError(f"unexpected import: {name}")

    with patch.object(registry_module.importlib, "import_module", side_effect=_import_module), \
         patch.object(registry_module.pkgutil, "iter_modules", return_value=[(None, "example", False)]), \
         patch.object(registry_module.logger, "exception") as mock_log:
        SkillRegistry.autodiscover("app.skills")

    mock_log.assert_called_once()


def test_skill_registry_autodiscover_surfaces_unexpected_submodule_import_errors() -> None:
    fake_package = SimpleNamespace(__path__=["/fake/skills"])

    def _import_module(name: str):
        if name == "app.skills":
            return fake_package
        if name == "app.skills.example":
            raise AssertionError("unexpected module bug")
        raise AssertionError(f"unexpected import: {name}")

    with patch.object(registry_module.importlib, "import_module", side_effect=_import_module), \
         patch.object(registry_module.pkgutil, "iter_modules", return_value=[(None, "example", False)]):
        with pytest.raises(AssertionError, match="unexpected module bug"):
            SkillRegistry.autodiscover("app.skills")
