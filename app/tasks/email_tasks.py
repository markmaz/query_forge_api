from app.celery_app import celery


@celery.task(name="send_invite_email_task")
def send_invite_email_task(email: str, user_id: str):
    from app import create_app
    app = create_app()

    with app.app_context():
        from app.email.mailer import send_invite_email
        send_invite_email(email, user_id)

@celery.task(name="send_otp_email_task")
def send_otp_email(email: str, otp: str):
    from app import create_app
    app = create_app()

    with app.app_context():
        from app.email.mailer import send_otp_code
        send_otp_code(email, otp)

@celery.task(name="send_password_reset")
def send_password_reset(email: str, token: str):
    from app import create_app
    app = create_app()

    with app.app_context():
        from app.email.mailer import send_password_reset
        send_password_reset(email, token)