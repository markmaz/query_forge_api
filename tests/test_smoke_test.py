# tests/test_smoke_test.py
from __future__ import annotations
import os
import sys
import types
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Import helpers — smoke_test.py lives in scripts/, not a package
# ---------------------------------------------------------------------------
import importlib.util, pathlib

_SCRIPT = pathlib.Path(__file__).parent.parent / "scripts" / "smoke_test.py"
spec = importlib.util.spec_from_file_location("smoke_test", _SCRIPT)
smoke = importlib.util.module_from_spec(spec)
sys.modules["smoke_test"] = smoke
spec.loader.exec_module(smoke)


class TestLoadConfig:
    def test_reads_required_vars_from_env(self, monkeypatch):
        monkeypatch.setenv("QF_BASE_URL", "http://api.example.com")
        monkeypatch.setenv("QF_USERNAME", "tester")
        monkeypatch.setenv("QF_PASSWORD", "secret")
        monkeypatch.setenv("QF_WORKSPACE_ID", "ws-1")
        cfg = smoke.load_config()
        assert cfg.base_url == "http://api.example.com"
        assert cfg.username == "tester"
        assert cfg.password == "secret"
        assert cfg.workspace_id == "ws-1"

    def test_raises_if_required_var_missing(self, monkeypatch):
        for var in ("QF_BASE_URL", "QF_USERNAME", "QF_PASSWORD", "QF_WORKSPACE_ID"):
            monkeypatch.delenv(var, raising=False)
        with pytest.raises(SystemExit):
            smoke.load_config()

    def test_cli_overrides_take_precedence(self, monkeypatch):
        monkeypatch.setenv("QF_BASE_URL", "http://from-env.example.com")
        monkeypatch.setenv("QF_USERNAME", "env-user")
        monkeypatch.setenv("QF_PASSWORD", "env-pass")
        monkeypatch.setenv("QF_WORKSPACE_ID", "ws-env")
        cfg = smoke.load_config(
            base_url="http://from-cli.example.com",
            username="cli-user",
        )
        assert cfg.base_url == "http://from-cli.example.com"
        assert cfg.username == "cli-user"
        # non-overridden fields still come from env
        assert cfg.password == "env-pass"


class TestAuthenticate:
    def _cfg(self):
        return smoke.SmokeConfig(
            base_url="http://api.example.com",
            username="tester",
            password="secret",
            workspace_id="ws-1",
        )

    def test_returns_token_on_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "tok-abc"}
        with patch("requests.post", return_value=mock_resp):
            token = smoke.authenticate(self._cfg())
        assert token == "tok-abc"

    def test_exits_on_401(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"message": "Invalid username or password"}
        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(SystemExit):
                smoke.authenticate(self._cfg())

    def test_posts_to_correct_endpoint(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "tok-xyz"}
        with patch("requests.post", return_value=mock_resp) as mock_post:
            smoke.authenticate(self._cfg())
        url = mock_post.call_args[0][0]
        assert url.endswith("/api/v1/auth/auth")
        payload = mock_post.call_args[1]["json"]
        assert payload["username"] == "tester"
        assert payload["password"] == "secret"
