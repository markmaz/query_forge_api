from __future__ import annotations

import app.tasks.email_tasks as email_tasks


class _App:
    def app_context(self):
        class _Ctx:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        return _Ctx()


def test_send_invite_email_task(monkeypatch):
    calls = []
    monkeypatch.setattr("app.create_app", lambda: _App())
    monkeypatch.setattr("app.email.mailer.send_invite_email", lambda email, user_id: calls.append((email, user_id)))

    email_tasks.send_invite_email_task("a@example.com", "u1")
    assert calls == [("a@example.com", "u1")]


def test_send_otp_email_task(monkeypatch):
    calls = []
    monkeypatch.setattr("app.create_app", lambda: _App())
    monkeypatch.setattr("app.email.mailer.send_otp_code", lambda email, otp: calls.append((email, otp)))

    email_tasks.send_otp_email("a@example.com", "1234")
    assert calls == [("a@example.com", "1234")]


def test_send_password_reset_task(monkeypatch):
    calls = []
    monkeypatch.setattr("app.create_app", lambda: _App())
    monkeypatch.setattr("app.email.mailer.send_password_reset", lambda email, token: calls.append((email, token)))

    email_tasks.send_password_reset("a@example.com", "tok")
    assert calls == [("a@example.com", "tok")]
