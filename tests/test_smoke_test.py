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


import requests as _requests

def _session(cfg=None):
    if cfg is None:
        cfg = smoke.SmokeConfig("http://api", "u", "p", "ws-1")
    s = _requests.Session()
    s.headers.update({"Authorization": "Bearer tok", "X-Workspace-Id": cfg.workspace_id})
    return s, cfg


class TestHttpHelpers:
    def _session(self):
        s = _requests.Session()
        s.headers.update({"Authorization": "Bearer tok", "X-Workspace-Id": "ws-1"})
        return s

    def test_get_returns_status_body_latency(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        with patch.object(_requests.Session, "get", return_value=mock_resp):
            status, body, latency = smoke._get(self._session(), "http://x/path")
        assert status == 200
        assert body == {"ok": True}
        assert isinstance(latency, int) and latency >= 0

    def test_get_returns_empty_body_on_json_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("not json")
        with patch.object(_requests.Session, "get", return_value=mock_resp):
            status, body, latency = smoke._get(self._session(), "http://x/path")
        assert status == 200
        assert body == {}

    def test_post_returns_status_body_latency(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"result": "ok"}
        with patch.object(_requests.Session, "post", return_value=mock_resp):
            status, body, latency = smoke._post(self._session(), "http://x/path", json={"q": "x"})
        assert status == 200
        assert body["result"] == "ok"

    def test_check_result_is_fail_on_bad_status(self):
        r = smoke.CheckResult(
            area="Infra", name="healthz",
            status=smoke.Status.FAIL, latency_ms=12, message="503"
        )
        assert r.status == smoke.Status.FAIL
        assert r.latency_ms == 12


class TestChecks1To7:
    def _ok(self, body=None):
        m = MagicMock()
        m.status_code = 200
        m.json.return_value = body or {}
        return m

    def _err(self, code=500):
        m = MagicMock()
        m.status_code = code
        m.json.return_value = {"error": "fail"}
        return m

    def test_check_healthz_pass(self):
        session, cfg = _session()
        with patch.object(session, "get", return_value=self._ok()):
            result = smoke.check_healthz(session, cfg)
        assert result.status == smoke.Status.PASS

    def test_check_healthz_fail(self):
        session, cfg = _session()
        with patch.object(session, "get", return_value=self._err(503)):
            result = smoke.check_healthz(session, cfg)
        assert result.status == smoke.Status.FAIL

    def test_check_health_detailed_pass(self):
        session, cfg = _session()
        body = {"overall": "healthy", "checks": {}}
        with patch.object(session, "get", return_value=self._ok(body)):
            result = smoke.check_health_detailed(session, cfg)
        assert result.status == smoke.Status.PASS

    def test_check_health_detailed_fail_when_unhealthy(self):
        session, cfg = _session()
        body = {"overall": "unhealthy", "checks": {}}
        with patch.object(session, "get", return_value=self._ok(body)):
            result = smoke.check_health_detailed(session, cfg)
        assert result.status == smoke.Status.FAIL

    def test_check_health_detailed_pass_when_degraded(self):
        # "degraded" is not "unhealthy" — should still pass
        session, cfg = _session()
        body = {"overall": "degraded", "checks": {}}
        with patch.object(session, "get", return_value=self._ok(body)):
            result = smoke.check_health_detailed(session, cfg)
        assert result.status == smoke.Status.PASS
        assert "degraded" in result.message

    def test_check_users_counts_pass(self):
        session, cfg = _session()
        with patch.object(session, "get", return_value=self._ok({"total": 5})):
            result = smoke.check_users_counts(session, cfg)
        assert result.status == smoke.Status.PASS

    def test_check_workspaces_pass(self):
        session, cfg = _session()
        body = {"workspaces": [{"id": "ws-1"}]}
        with patch.object(session, "get", return_value=self._ok(body)):
            result = smoke.check_workspaces(session, cfg)
        assert result.status == smoke.Status.PASS

    def test_check_workspaces_fail_when_empty(self):
        session, cfg = _session()
        with patch.object(session, "get", return_value=self._ok({"workspaces": []})):
            result = smoke.check_workspaces(session, cfg)
        assert result.status == smoke.Status.FAIL

    def test_simple_checks_pass_on_200(self):
        # checks 5, 6, 7 just need HTTP 200
        for fn in (smoke.check_semantic_concepts, smoke.check_semantic_registry, smoke.check_domains):
            session, cfg = _session()
            with patch.object(session, "get", return_value=self._ok()):
                result = fn(session, cfg)
            assert result.status == smoke.Status.PASS, f"{fn.__name__} should pass on 200"

    def test_simple_checks_fail_on_non_200(self):
        for fn in (smoke.check_semantic_concepts, smoke.check_semantic_registry, smoke.check_domains):
            session, cfg = _session()
            with patch.object(session, "get", return_value=self._err()):
                result = fn(session, cfg)
            assert result.status == smoke.Status.FAIL, f"{fn.__name__} should fail on 500"
