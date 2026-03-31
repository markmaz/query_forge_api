from __future__ import annotations

import time
from typing import Any, Callable

from app.models.tenancy.user import User


class PasswordResetService:
    def __init__(
        self,
        *,
        cache,
        ttl_seconds: int,
        token_generator: Callable[[str], str],
        cache_key: Callable[[str], str],
        cache_key_from_hashed: Callable[[str], str],
        user_service_factory: Callable[[], Any],
        send_password_reset_task,
    ) -> None:
        self._cache = cache
        self._ttl_seconds = ttl_seconds
        self._token_generator = token_generator
        self._cache_key = cache_key
        self._cache_key_from_hashed = cache_key_from_hashed
        self._user_service_factory = user_service_factory
        self._send_password_reset_task = send_password_reset_task

    def send_reset_request(self, email: str) -> tuple[str, int]:
        user = self._user_service_factory().find_user_by_username(email)
        if user:
            token = self._token_generator(user.user_id)
            key = self._cache_key(token)
            self._cache.hset(
                key,
                mapping={
                    "user_id": user.user_id,
                    "purpose": "password_reset",
                    "created": str(int(time.time())),
                    "attempts": "0",
                },
            )
            self._cache.expire(key, self._ttl_seconds)
            self._send_password_reset_task.delay(user.email, token)
        return "", 204

    def validate_token(self, token: str):
        return self._cache.exists(self._cache_key(token))

    def reset_password(self, password: str, hashed_token: str):
        key = self._cache_key_from_hashed(hashed_token)

        pipeline = self._cache.pipeline()
        pipeline.hgetall(key)
        pipeline.delete(key)
        data, _ = pipeline.execute()

        if not data or data.get("purpose") != "password_reset":
            return "", 400

        user_id = data.get("user_id")
        user = User(user_id=user_id, password=password)
        updated = self._user_service_factory().update_user(user_id, user)
        if updated:
            return "", 204
        return "", 400
