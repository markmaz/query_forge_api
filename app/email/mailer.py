from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from flask import current_app, render_template
from flask_mail import Message

from app.config import INVITE_URL, PASSWORD_RESET_URL
from app.extensions import mail
from app.utils.token_utils import generate_token

logger = logging.getLogger(__name__)

_LOGO_FILENAME = "qf-logo.png"
_LOGO_CONTENT_ID = "<logo>"
_LOGO_MIME_TYPE = "image/png"


@dataclass(frozen=True)
class _RenderedEmail:
    subject: str
    html: str


def send_invite_email(to_email: str, user_id: str) -> None:
    token = generate_token(user_id)
    invite_url = f"{INVITE_URL}?token={token}"
    rendered = _RenderedEmail(
        subject="You've been invited to join QueryForge!",
        html=render_template("/email_invitation/invite_user.html", invite_url=invite_url),
    )
    send_email(get_logo(), rendered.subject, to_email, rendered.html)


def send_otp_code(to_email: str, otp: str) -> None:
    rendered = _RenderedEmail(
        subject=f"QueryForge - Your verification code is {otp}",
        html=render_template("/otp_verification/otp_verification.html", otp=otp),
    )
    send_email(get_logo(), rendered.subject, to_email, rendered.html)


def send_password_reset(to_email: str, token: str) -> None:
    reset_url = f"{PASSWORD_RESET_URL}?token={token}"
    rendered = _RenderedEmail(
        subject="QueryForge - Password Reset",
        html=render_template("/email_password_reset/password_reset.html", password_reset_url=reset_url),
    )
    send_email(get_logo(), rendered.subject, to_email, rendered.html)


def send_email(logo_path: str, subject: str, to_email: str, html: str) -> None:
    message = Message(subject=subject, recipients=[to_email], html=html)
    _attach_logo(message, logo_path)
    mail.send(message)


def _attach_logo(message: Message, logo_path: str) -> None:
    with open(logo_path, "rb") as file_handle:
        logo_bytes = file_handle.read()

    message.attach(
        filename=_LOGO_FILENAME,
        content_type=_LOGO_MIME_TYPE,
        data=logo_bytes,
        disposition="inline",
        headers={"Content-ID": _LOGO_CONTENT_ID},
    )


def get_logo() -> str:
    return os.path.join(current_app.root_path, "static", "images", "qf_logo.png")
