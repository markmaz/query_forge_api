from __future__ import annotations

from app.services.tenancy.secret_resolver import SecretResolver


def test_resolve_env_secret(monkeypatch):
    monkeypatch.setenv("QF_TEST_SECRET", "abc123")
    resolver = SecretResolver()
    assert resolver.resolve("env:QF_TEST_SECRET") == "abc123"


def test_resolve_unknown_format_returns_none():
    resolver = SecretResolver()
    assert resolver.resolve("vault:foo/bar") is None
    assert resolver.resolve("kms:key-1") is None


def test_inject_if_missing():
    resolver = SecretResolver()
    cfg = {"host": "x"}
    out = resolver.inject_if_missing(cfg, secret_ref=None, key="token")
    assert out == cfg


def test_inject_if_missing_resolves_env_secret(monkeypatch):
    monkeypatch.setenv("QF_DSN_SECRET", "top-secret")
    resolver = SecretResolver()
    out = resolver.inject_if_missing({"account": "a"}, secret_ref="env:QF_DSN_SECRET", key="password")
    assert out["password"] == "top-secret"
