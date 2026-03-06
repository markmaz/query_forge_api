from __future__ import annotations

import os
import uuid
from typing import Any, Optional

import redis

from app.config import VALKEY_CONFIG

LOGIN_CHALLENGE_TTL_S = int(os.getenv("LOGIN_CHALLENGE_TTL_SECONDS", "300"))
_LOGIN_CHALLENGE_PREFIX = "login:challenge:"


class LoginChallengeService:
    def __init__(self, *, redis_client: Any | None = None) -> None:
        self._redis = redis_client or redis.Redis.from_url(VALKEY_CONFIG, decode_responses=True)

    def create_challenge(self, user_id: str) -> str:
        challenge_id = uuid.uuid4().hex
        self._redis.setex(self._challenge_key(challenge_id), LOGIN_CHALLENGE_TTL_S, str(user_id))
        return challenge_id

    def consume_challenge(self, challenge_id: str) -> Optional[str]:
        key = self._challenge_key(challenge_id)
        pipe = self._redis.pipeline()
        pipe.get(key)
        pipe.delete(key)
        user_id, _deleted = pipe.execute()
        user_text = str(user_id or "").strip()
        return user_text or None

    @staticmethod
    def _challenge_key(challenge_id: str) -> str:
        cid = str(challenge_id or "").strip()
        return f"{_LOGIN_CHALLENGE_PREFIX}{cid}"
