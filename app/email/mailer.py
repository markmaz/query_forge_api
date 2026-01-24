import logging
import os

from flask import current_app, render_template
from flask_mail import Message

from app import mail
from app.config import INVITE_URL, PASSWORD_RESET_URL
from app.utils.token_utils import generate_token

logger = logging.getLogger(__name__)

def send_invite_email(to_email: str, user_id: str):
    subject = "You've been invited to join QueryForge!"

    token = generate_token(user_id)
    url = f"{INVITE_URL}?token={token}" 
    html = render_template("/email_invitation/invite_user.html", invite_url=url)

    send_email(get_logo(), subject, to_email, html)

def send_otp_code(to_email: str, otp: str):
    subject = f"QueryForge - Your verification code is {otp}"
    html = render_template("/otp_verification/otp_verification.html", otp = otp)
    send_email(get_logo(), subject, to_email, html)

def send_password_reset(to_email: str, token: str):
    subject = "QueryForge - Password Reset"
    url = f"{PASSWORD_RESET_URL}?token={token}"
    html = render_template("/email_password_reset/password_reset.html", password_reset_url=url)
    send_email(get_logo(), subject, to_email, html)

def send_email(logo_path: str, subject: str, to_email: str, html: str):
    msg = Message(subject=subject, recipients=[to_email], html=html)

    with open(logo_path, 'rb') as fp:
                msg.attach(
            filename="qf-logo.png",
            content_type="image/png",
            data=fp.read(),
            disposition="inline",
            headers={'Content-ID': '<logo>'}
        )
    mail.send(msg)

def get_logo() -> str:
      return  os.path.join(current_app.root_path, 'static', 'images', 'qf_logo.png')