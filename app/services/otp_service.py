
import pyotp
import redis

from app.config import VALKEY_ADDRESS, VALKEY_PORT
from app.services.auth_service import AuthService
from app.services.user_service import UserService

r = redis.Redis(host=VALKEY_ADDRESS, port=VALKEY_PORT, db=0)

def generate_otp(user_id: str) -> str:
    user_service = UserService()
    user = user_service.get_user(user_id)

    if user:
        totp = pyotp.TOTP(user.otp_secret)
        code = totp.now()

        from app.tasks.email_tasks import send_otp_email
        send_otp_email.delay(user.email, code)

        return code

def verify_otp(user_id: str, otp: str) -> bool:
    user_service = UserService()
    user = user_service.get_user(user_id)
    
    if user:
        if not user.otp_secret:
            return False
        totp = pyotp.TOTP(user.otp_secret)
        if totp.verify(otp, valid_window=1):
            auth = AuthService()
            return auth.generate_token(user)
