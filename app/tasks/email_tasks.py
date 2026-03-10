from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.celery_app import celery


@celery.task(name="qf.email.invite")
def send_invite_email_task(email: str, user_id: str) -> None:
    _run_mail_action(lambda: _send_invite(email, user_id))


@celery.task(name="qf.email.otp")
def send_otp_email(email: str, otp: str) -> None:
    _run_mail_action(lambda: _send_otp(email, otp))


@celery.task(name="qf.email.password_reset")
def send_password_reset(email: str, token: str) -> None:
    _run_mail_action(lambda: _send_reset(email, token))


def _run_mail_action(action: Callable[[], Any]) -> None:
    from app import create_app

    app = create_app()
    with app.app_context():
        action()


def _send_invite(email: str, user_id: str) -> None:
    from app.email.mailer import send_invite_email

    send_invite_email(email, user_id)


def _send_otp(email: str, otp: str) -> None:
    from app.email.mailer import send_otp_code

    send_otp_code(email, otp)


def _send_reset(email: str, token: str) -> None:
    from app.email.mailer import send_password_reset as send_password_reset_email

    send_password_reset_email(email, token)
