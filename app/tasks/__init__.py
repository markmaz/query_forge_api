from app.tasks.email_tasks import send_invite_email_task as send_invite_email_task
from app.tasks.email_tasks import send_otp_email as send_otp_email
from app.tasks.email_tasks import send_password_reset as send_password_reset

QF_TASK_PREFIX = "qf"

__all__ = ["send_invite_email_task", "send_otp_email", "send_password_reset"]
