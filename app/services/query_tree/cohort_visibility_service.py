from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor


@dataclass(frozen=True)
class CohortSummary:
    query_id: str
    workspace_id: str
    owner_user_id: Optional[str]
    title: str
    prompt: Optional[str]
    updated_at: Optional[datetime]
    access_via: str
    can_edit: bool


class CohortVisibilityService:
    def __init__(self, *, workspace_id: str, user_id: str, sql: Optional[SQLExecutor] = None) -> None:
        if not workspace_id:
            raise ServiceError("workspace_id is required", status_code=400)
        if not user_id:
            raise ServiceError("user_id is required", status_code=400)
        self._workspace_id = workspace_id
        self._user_id = user_id
        self._sql = sql or MySQLSQLExecutor()

    def list_visible(self) -> Dict[str, Any]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              q.id AS query_id,
              q.workspace_id,
              q.owner_user_id,
              q.title,
              q.sql_json,
              q.updated_at,
              MAX(CASE WHEN a.permission = 'WRITE' THEN 1 ELSE 0 END) AS can_edit,
              MAX(CASE WHEN a.id IS NOT NULL THEN 1 ELSE 0 END) AS has_share
            FROM saved_query q
            LEFT JOIN saved_query_acl a
              ON a.saved_query_id = q.id
             AND a.workspace_id = :ws
             AND (
               (a.principal_type = 'WORKSPACE' AND a.principal_id = :ws)
               OR
               (a.principal_type = 'USER' AND a.principal_id = :uid)
             )
            WHERE q.workspace_id = :ws
              AND q.scope = 'MINE'
              AND q.is_deleted = 0
              AND (q.owner_user_id = :uid OR a.id IS NOT NULL)
            GROUP BY q.id
            ORDER BY q.updated_at DESC, q.title ASC
            """,
            {"ws": self._workspace_id, "uid": self._user_id},
        )

        cohorts: List[CohortSummary] = []
        has_shared = False

        for row in rows:
            sql_json = row.get("sql_json")
            tool = self._tool_from_sql_json(sql_json)
            if tool != "cohort_builder":
                continue

            owner_user_id = (row.get("owner_user_id") or None)
            is_owner = owner_user_id == self._user_id
            access_via = "owner" if is_owner else "share"
            can_edit = is_owner or bool(int(row.get("can_edit") or 0))

            if not is_owner:
                has_shared = True

            cohorts.append(
                CohortSummary(
                    query_id=str(row["query_id"]),
                    workspace_id=str(row["workspace_id"]),
                    owner_user_id=str(owner_user_id) if owner_user_id else None,
                    title=str(row["title"]),
                    prompt=self._prompt_from_sql_json(sql_json),
                    updated_at=row.get("updated_at"),
                    access_via=access_via,
                    can_edit=can_edit,
                )
            )

        return {
            "cohorts": [
                {
                    "queryId": c.query_id,
                    "workspaceId": c.workspace_id,
                    "ownerUserId": c.owner_user_id,
                    "title": c.title,
                    "prompt": c.prompt,
                    "updatedAt": _format_datetime(c.updated_at),
                    "accessVia": c.access_via,
                    "canEdit": c.can_edit,
                }
                for c in cohorts
            ],
            "hasShared": has_shared,
        }

    def _tool_from_sql_json(self, sql_json: Optional[Any]) -> Optional[str]:
        parsed = self._parse_sql_json(sql_json)
        if not parsed:
            return None
        meta = parsed.get("meta")
        if not isinstance(meta, dict):
            return None
        tool = meta.get("tool")
        return str(tool) if tool else None

    def _prompt_from_sql_json(self, sql_json: Optional[Any]) -> Optional[str]:
        parsed = self._parse_sql_json(sql_json)
        if not parsed:
            return None

        candidates = [
            parsed.get("prompt"),
            (parsed.get("meta") or {}).get("prompt") if isinstance(parsed.get("meta"), dict) else None,
            (parsed.get("input") or {}).get("prompt") if isinstance(parsed.get("input"), dict) else None,
            parsed.get("nlPrompt"),
            parsed.get("naturalLanguagePrompt"),
        ]
        for value in candidates:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    def _parse_sql_json(self, sql_json: Optional[Any]) -> Optional[Dict[str, Any]]:
        if not sql_json:
            return None
        if isinstance(sql_json, str):
            try:
                sql_json = json.loads(sql_json)
            except Exception:
                return None
        return sql_json if isinstance(sql_json, dict) else None


def _format_datetime(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
