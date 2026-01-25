from __future__ import annotations

import io

import pytest

from app.email import mailer


class _DummyMail:
    def __init__(self) -> None:
        self.sent = []

    def send(self, msg) -> None:
        self.sent.append(msg)


class _DummyFile(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_get_logo(app) -> None:
    with app.app_context():
        path = mailer.get_logo()
        assert path.endswith("static/images/qf_logo.png")


def test_send_email_sends(monkeypatch: pytest.MonkeyPatch, app) -> None:
    dummy_mail = _DummyMail()
    monkeypatch.setattr(mailer, "mail", dummy_mail)
    monkeypatch.setattr("builtins.open", lambda *_a, **_k: _DummyFile(b"img"))
    with app.app_context():
        mailer.send_email("logo.png", "Subject", "a@example.com", "<html />")
    assert dummy_mail.sent


def test_send_invite_email(monkeypatch: pytest.MonkeyPatch, app) -> None:
    monkeypatch.setattr(mailer, "generate_token", lambda _uid: "tok")
    monkeypatch.setattr(mailer, "render_template", lambda *_a, **_k: "<html />")
    calls = {}

    def _send_email(logo_path, subject, to_email, html):
        calls["subject"] = subject
        calls["to"] = to_email
        calls["html"] = html

    monkeypatch.setattr(mailer, "send_email", _send_email)
    with app.app_context():
        mailer.send_invite_email("a@example.com", "u1")
    assert calls["to"] == "a@example.com"


def test_send_otp_code(monkeypatch: pytest.MonkeyPatch, app) -> None:
    monkeypatch.setattr(mailer, "render_template", lambda *_a, **_k: "<html />")
    calls = {}

    def _send_email(logo_path, subject, to_email, html):
        calls["subject"] = subject
        calls["to"] = to_email
        calls["html"] = html

    monkeypatch.setattr(mailer, "send_email", _send_email)
    with app.app_context():
        mailer.send_otp_code("a@example.com", "123456")
    assert "verification code" in calls["subject"]


def test_send_password_reset(monkeypatch: pytest.MonkeyPatch, app) -> None:
    monkeypatch.setattr(mailer, "render_template", lambda *_a, **_k: "<html />")
    calls = {}

    def _send_email(logo_path, subject, to_email, html):
        calls["subject"] = subject
        calls["to"] = to_email
        calls["html"] = html

    monkeypatch.setattr(mailer, "send_email", _send_email)
    with app.app_context():
        mailer.send_password_reset("a@example.com", "tok")
    assert "Password Reset" in calls["subject"]
