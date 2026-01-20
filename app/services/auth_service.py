import datetime
import hashlib
import logging
import time
from typing import Optional

import jwt
import redis
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from werkzeug.security import check_password_hash

from app.config import JWT_ALGORITHM, JWT_EXP_DELTA_HOURS, JWT_SECRET, VALKEY_CONFIG
from app.decorators.validate import validate_params
from app.exceptions.service_error import ServiceError
from app.models.user import User
from app.services.user_service import UserService
from app.utils.token_utils import generate_token as generate

cache = redis.Redis.from_url(VALKEY_CONFIG, decode_responses=True)
logger = logging.getLogger(__name__)
TTL_SECONDS = 3600
KEY_PREFIX = "reset:token:"

def hash_token(t):
    return hashlib.sha256(t.encode()).hexdigest()

def cache_key(t):
    return get_cache_key(hash_token(t))

def get_cache_key(hashed_token):
    return f"{KEY_PREFIX}{hashed_token}"

class AuthService:
    def __init__(self):
        self.secret = JWT_SECRET
        self.algorithm = JWT_ALGORITHM
        self.exp_delta = datetime.timedelta(hours=JWT_EXP_DELTA_HOURS)
    
    def _norm_status(self, s: object) -> str:
        return (str(s or "")).strip().lower()
    
    
    @validate_params("username", "password")
    def non_interactive_authentication(self, username: str, password: str) -> dict:
        """
        Authenticates user and returns a JWT token if valid.
        
        :param username: The user's username
        :param password: The password for the user

        :return: A JWT token as a string
        :raises ServiceError: When the user is not found or authenticated.
        :raises SQLAlchemyError: When the database operation fails.
        """
        conn = None

        try:
            user_service = UserService()
            user = user_service.get_user_by_username(username)
            status = self._norm_status(user.status)

            if user and status in "deactivated":
                logger.error(f"User {username} with status {status} is not an activce user.")
                raise ServiceError("User is not active.", 404)
            
            if user and check_password_hash(user.password, password):
                user_service.update_last_login(user.user_id)
                return user
            else:
                logger.error(f"User not found: {username}")
                raise ServiceError("User not authenticated", 404)
        except OperationalError as e:
            logger.error(f"Operation failed: {str(e)}")
            raise ServiceError("Operation failed: Connection failure.", 500)
        except SQLAlchemyError as e:
            logger.error(f"Operation failed: {str(e)}")
            raise ServiceError("Database operation failed: Database failure.", 500)
        finally:
            if conn:
                conn.close()

    
    @validate_params("username", "password")
    def authenticate(self, username: str, password: str) -> dict:
        """
        Authenticates user and returns a JWT token if valid.
        
        :param username: The user's username
        :param password: The password for the user

        :return: A JWT token as a string
        :raises ServiceError: When the user is not found or authenticated.
        :raises SQLAlchemyError: When the database operation fails.
        """
        conn = None

        try:
            user_service = UserService()
            user = user_service.get_user_by_username(username)
            status = self._norm_status(user.status)

            if user and status in "deactivated":
                logger.error(f"User {username} with status {status} is not an activce user.")
                raise ServiceError("User is not active.", 404)
            
            if user and check_password_hash(user.password, password):
                user_service.update_last_login(user.user_id)
                return {"user_id": user.user_id, "requires_otp": True, "email": user.email}
            else:
                logger.error(f"User not found: {username}")
                raise ServiceError("User not authenticated", 404)
        except OperationalError as e:
            logger.error(f"Operation failed: {str(e)}")
            raise ServiceError("Operation failed: Connection failure.", 500)
        except SQLAlchemyError as e:
            logger.error(f"Operation failed: {str(e)}")
            raise ServiceError("Database operation failed: Database failure.", 500)
        finally:
            if conn:
                conn.close()

    @validate_params("user")    
    def generate_token(self, user: User) -> str:
        """
        Generates JWT token for the user.

        :param user: A dictionary representing a user object

        :return: An encoded JWT token as a string
        :raises ServiceError: If the user data is invalid
        """
        payload = {
            "sub": user.user_id,  # Use 'sub' as the standard JWT subject
            "username": user.user_name,
            "exp": datetime.datetime.utcnow() + self.exp_delta
        }

        return jwt.encode(payload, self.secret, algorithm=self.algorithm)
    

    @validate_params("token")
    def verify_token(self, token: str) -> Optional[str]:
        """
        Verifies JWT and returns user ID if valid, else None.
        
        :param token: The JWT token

        :return: The user ID from the payload if valid, otherwise None
        :raises jwt.ExpiredSignatureError: When the token has expired. 
        :raises jwt.InvalidTokenError: When the token is invalid or malformed.
        """
        try:
            return jwt.decode(token, self.secret, algorithms=[self.algorithm])
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None

    @validate_params("email")
    def send_reset_request(self, email: str) -> dict:
        service = UserService()
        user = service.get_user_by_username(email)

        if user:
            token = generate(user.user_id)
            key = cache_key(token)

            cache.hset(key, mapping={
                "user_id": user.user_id,
                "purpose": "password_reset",
                "created": str(int(time.time())),
                "attempts": "0",
             })
            
            cache.expire(key, TTL_SECONDS)

            from app.tasks.email_tasks import send_password_reset
            send_password_reset.delay(user.email, token)

        return ("", 204)
    
    @validate_params("token")
    def validate_token(self, token: str):
        return cache.exists(cache_key(token))

    @validate_params("password", "hashed_token")
    def reset_password(self, password: str, hashed_token: str):
        key = get_cache_key(hashed_token)

        pipe = cache.pipeline()
        pipe.hgetall(key)
        pipe.delete(key)

        data, _ = pipe.execute()
        
        if not data or data.get("purpose") != "password_reset":
            return ("", 400)
        
        user_id = data.get("user_id")

        user = User(user_id=user_id, password=password)
        service = UserService()
        updated_user = service.update_user(user_id, user)

        if updated_user:
            return ("", 204)
