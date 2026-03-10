from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import (
    QF_FORGE_INSIGHTS_ROUTE_FEWSHOT_CACHE_SECONDS,
    QF_FORGE_INSIGHTS_ROUTE_FEWSHOT_ENABLED,
    QF_FORGE_INSIGHTS_ROUTE_FEWSHOT_LIMIT,
    QF_FORGE_INSIGHTS_ROUTE_FEWSHOT_MAX_PROMPT_CHARS,
    QF_FORGE_INSIGHTS_ROUTE_FEWSHOT_SCAN_LIMIT,
)
from app.ports.sql_executor import ForgeQueryPort


class EducationFewshotService:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        enabled: bool = QF_FORGE_INSIGHTS_ROUTE_FEWSHOT_ENABLED,
        limit: int = QF_FORGE_INSIGHTS_ROUTE_FEWSHOT_LIMIT,
        scan_limit: int = QF_FORGE_INSIGHTS_ROUTE_FEWSHOT_SCAN_LIMIT,
        cache_seconds: int = QF_FORGE_INSIGHTS_ROUTE_FEWSHOT_CACHE_SECONDS,
        max_prompt_chars: int = QF_FORGE_INSIGHTS_ROUTE_FEWSHOT_MAX_PROMPT_CHARS,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._enabled = bool(enabled)
        self._limit = max(1, min(int(limit), 20))
        self._scan_limit = max(self._limit, min(int(scan_limit), 500))
        self._cache_seconds = max(0, int(cache_seconds))
        self._max_prompt_chars = max(40, int(max_prompt_chars))
        self._cache: Dict[str, Tuple[float, List[str]]] = {}

    def get_examples(self, *, workspace_id: str, user_id: str) -> List[str]:
        del user_id  # Workspace-level thumbs-up prompts are sufficient for routing.
        if not self._enabled:
            return []
        ws = str(workspace_id or "").strip()
        if ws == "":
            return []
        now = time.time()
        cached = self._cache.get(ws)
        if cached and cached[0] > now:
            return list(cached[1])

        rows = self._fetch_rows(ws)
        out: List[str] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            payload = _parse_json_obj(row.get("response_json"))
            if not _is_education_payload(payload):
                continue
            prompt = _best_prompt(row, max_prompt_chars=self._max_prompt_chars)
            if prompt is None:
                continue
            normalized = prompt.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            out.append(prompt)
            if len(out) >= self._limit:
                break

        if self._cache_seconds > 0:
            self._cache[ws] = (now + self._cache_seconds, list(out))
        return out

    def _fetch_rows(self, workspace_id: str) -> List[Dict[str, Any]]:
        try:
            return self._sql.execute_query_mappings(
                """
                SELECT normalized_prompt, prompt_text, response_json, updated_at
                FROM prompt_feedback
                WHERE workspace_id = :workspace_id
                  AND vote = 'up'
                  AND (normalized_prompt IS NOT NULL OR prompt_text IS NOT NULL)
                ORDER BY updated_at DESC
                LIMIT :scan_limit
                """,
                {"workspace_id": workspace_id, "scan_limit": self._scan_limit},
            )
        except Exception:
            return []


def _best_prompt(row: Mapping[str, Any], *, max_prompt_chars: int) -> Optional[str]:
    for key in ("normalized_prompt", "prompt_text"):
        raw = row.get(key)
        text = str(raw or "").strip()
        if text:
            compact = " ".join(text.split())
            return compact[:max_prompt_chars]
    return None


def _parse_json_obj(value: Any) -> Optional[Dict[str, Any]]:
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            value = bytes(value).decode("utf-8", errors="ignore")
        except Exception:
            return None
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
        try:
            parsed = json.loads(text)
        except Exception:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def _is_education_payload(payload: Optional[Mapping[str, Any]]) -> bool:
    if not isinstance(payload, Mapping):
        return False
    mode = str(payload.get("mode") or "").strip().lower()
    if mode == "education_pipeline":
        return True
    route = str(payload.get("route") or "").strip().lower()
    if route in {"plan_domain", "education_pipeline"}:
        return True
    plan = payload.get("plan_json_v2")
    if isinstance(plan, Mapping):
        vertical = str(plan.get("vertical_norm") or "").strip().lower()
        if vertical == "education":
            return True
    return False


__all__ = ["EducationFewshotService"]
