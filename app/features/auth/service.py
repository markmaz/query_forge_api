from __future__ import annotations

from typing import Any, Dict
from urllib.parse import unquote

from flask import request

from app.config import COOKIE_SAMESITE, COOKIE_SECURE, REFRESH_COOKIE_PATH


class AuthFeatureService:
    def extract_default_workspace_id(self, user: Any) -> str | None:
        workspaces = getattr(user, "workspaces", None) or []
        default_ws = next((w for w in workspaces if getattr(w, "is_default", False)), None)
        workspace_id = getattr(default_ws, "workspace_id", None)
        if workspace_id is None:
            return None
        return str(workspace_id)

    def extract_invite_token(self, body: Dict[str, Any]) -> str:
        body_token = str((body or {}).get("token") or "").strip()
        if body_token:
            return body_token
        return str(request.args.get("token") or "").strip()

    def clear_legacy_refresh_cookies(self, response) -> None:
        for legacy_path in ("/", "/api/v1"):
            if legacy_path == REFRESH_COOKIE_PATH:
                continue
            response.set_cookie(
                "refresh_token",
                "",
                httponly=True,
                secure=bool(COOKIE_SECURE),
                samesite=COOKIE_SAMESITE,
                max_age=0,
                path=legacy_path,
            )

    def set_refresh_cookie(self, response, refresh_token: str, max_age: int) -> None:
        response.set_cookie(
            "refresh_token",
            refresh_token,
            httponly=True,
            secure=bool(COOKIE_SECURE),
            samesite=COOKIE_SAMESITE,
            max_age=max_age,
            path=REFRESH_COOKIE_PATH,
        )
        self.clear_legacy_refresh_cookies(response)

    def get_refresh_candidates_from_request(self) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            if token and token not in seen:
                seen.add(token)
                values.append(token)

        raw_cookie = request.headers.get("Cookie", "")
        for chunk in raw_cookie.split(";"):
            name, sep, value = chunk.partition("=")
            if sep == "" or name.strip() != "refresh_token":
                continue
            token = unquote(value.strip().strip('"'))
            if token and token not in seen:
                seen.add(token)
                values.append(token)

        parsed_cookie = request.cookies.get("refresh_token")
        if parsed_cookie and parsed_cookie not in seen:
            seen.add(parsed_cookie)
            values.append(parsed_cookie)

        return values


auth_feature_service = AuthFeatureService()
