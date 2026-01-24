import datetime
import hashlib
import logging
import time
import uuid
from typing import Any, Dict, Optional, Tuple

import jwt
import redis
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from werkzeug.security import check_password_hash

from app.config import (
    ACCESS_TOKEN_TTL_SECONDS,
    JWT_ALGORITHM,
    JWT_EXP_DELTA_HOURS,
    JWT_LEEWAY_SECONDS,
    JWT_SECRET,
    JWT_VERIFY_IAT,
    REFRESH_TOKEN_TTL_SECONDS,
    VALKEY_CONFIG,
)
from app.decorators.validate import validate_params
from app.exceptions.service_error import ServiceError
from app.models.user import User
from app.services.user_service import UserService
from app.utils.token_utils import generate_token as generate

cache = redis.Redis.from_url(VALKEY_CONFIG, decode_responses=True)
logger = logging.getLogger(__name__)
TTL_SECONDS = 3600
KEY_PREFIX = "reset:token:"
REFRESH_PREFIX = "auth:refresh:"
DEFAULT_LEEWAY_SECONDS = 30

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
        self.access_ttl_seconds = int(ACCESS_TOKEN_TTL_SECONDS or (JWT_EXP_DELTA_HOURS * 3600))
        self.refresh_ttl_seconds = int(REFRESH_TOKEN_TTL_SECONDS or (14 * 24 * 3600))
        self.leeway_seconds = int(JWT_LEEWAY_SECONDS or DEFAULT_LEEWAY_SECONDS)
        self.verify_iat = bool(JWT_VERIFY_IAT)
    
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
        return self.generate_access_token(
            user.user_id,
            extra_claims={"username": user.user_name},
        )

    def _encode(self, payload: Dict[str, Any]) -> str:
        return jwt.encode(payload, self.secret, algorithm=self.algorithm)

    def _decode(self, token: str) -> Dict[str, Any]:
        return jwt.decode(
            token,
            self.secret,
            algorithms=[self.algorithm],
            leeway=self.leeway_seconds,
            options={"verify_iat": self.verify_iat},
        )

    def _log_token_timing(self, payload: Dict[str, Any], context: str) -> None:
        iat = payload.get("iat")
        exp = payload.get("exp")
        if isinstance(iat, datetime.datetime):
            iat = int(iat.timestamp())
        if isinstance(exp, datetime.datetime):
            exp = int(exp.timestamp())
        now_ts = int(datetime.datetime.utcnow().timestamp())
        logger.debug(
            "Token timing (%s): sub=%s typ=%s iat=%s exp=%s now=%s leeway=%s",
            context,
            payload.get("sub"),
            payload.get("typ"),
            iat,
            exp,
            now_ts,
            self.leeway_seconds,
        )

    def decode_and_verify(self, token: str, *, expected_typ: Optional[str] = None) -> Dict[str, Any]:
        try:
            payload = self._decode(token)
        except jwt.ExpiredSignatureError as exc:
            logger.warning("JWT decode failed: expired token")
            raise ServiceError("Token expired", status_code=401) from exc
        except jwt.InvalidTokenError as exc:
            logger.warning("JWT decode failed: %s", exc)
            raise ServiceError("Invalid token", status_code=401) from exc

        if expected_typ:
            if payload.get("typ") != expected_typ:
                raise ServiceError("Invalid token type", status_code=401)
        self._log_token_timing(payload, "decode_and_verify")
        return payload

    def generate_access_token(self, user_id: str, extra_claims: Optional[Dict[str, Any]] = None) -> str:
        now = datetime.datetime.utcnow()
        payload = {
            "sub": str(user_id),
            "typ": "access",
            "jti": uuid.uuid4().hex,
            "iat": int(now.timestamp()),
            "exp": now + datetime.timedelta(seconds=self.access_ttl_seconds),
        }
        if extra_claims:
            payload.update(extra_claims)
        return self._encode(payload)

    def _generate_refresh_token_with_jti(self, user_id: str) -> Tuple[str, str]:
        now = datetime.datetime.utcnow()
        jti = uuid.uuid4().hex
        payload = {
            "sub": str(user_id),
            "typ": "refresh",
            "jti": jti,
            "iat": int(now.timestamp()),
            "exp": now + datetime.timedelta(seconds=self.refresh_ttl_seconds),
        }
        return self._encode(payload), jti

    def generate_refresh_token(self, user_id: str) -> str:
        token, _jti = self._generate_refresh_token_with_jti(user_id)
        return token

    def store_refresh_jti(self, jti: str, user_id: str, ttl_seconds: int) -> None:
        key = f"{REFRESH_PREFIX}{jti}"
        cache.setex(key, int(ttl_seconds), str(user_id))

    def revoke_refresh_jti(self, jti: str) -> None:
        cache.delete(f"{REFRESH_PREFIX}{jti}")

    def is_refresh_jti_valid(self, jti: str) -> bool:
        return bool(cache.exists(f"{REFRESH_PREFIX}{jti}"))

    def issue_tokens(self, user: User) -> Dict[str, Any]:
        access_token = self.generate_access_token(
            user.user_id,
            extra_claims={"username": user.user_name},
        )
        refresh_token, jti = self._generate_refresh_token_with_jti(user.user_id)
        self.store_refresh_jti(jti, user.user_id, self.refresh_ttl_seconds)
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": self.access_ttl_seconds,
        }

    def rotate_refresh_token(self, refresh_token: str) -> Tuple[str, str]:
        payload = self.decode_and_verify(refresh_token, expected_typ="refresh")
        jti = payload.get("jti")
        if not jti:
            raise ServiceError("Invalid refresh token", status_code=401)
        if not self.is_refresh_jti_valid(jti):
            raise ServiceError("Refresh token revoked", status_code=401)
        user_id = str(payload.get("sub") or "")
        if not user_id:
            raise ServiceError("Invalid refresh token", status_code=401)

        self.revoke_refresh_jti(jti)
        new_refresh_token, new_jti = self._generate_refresh_token_with_jti(user_id)
        self.store_refresh_jti(new_jti, user_id, self.refresh_ttl_seconds)
        return new_refresh_token, user_id
    

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
            payload = self._decode(token)
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
        if payload.get("typ") != "access":
            return None
        self._log_token_timing(payload, "verify_token")
        return payload

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
