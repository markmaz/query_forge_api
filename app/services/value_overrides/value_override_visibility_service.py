from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.models.value_override import ValueOverrideListIndex, ValueOverrideMeta, ForgeSectionKey
from app.ports.sql_executor import ForgeQueryPort


@dataclass(frozen=True)
class ValueOverrideVisibilityResult:
    index: ValueOverrideListIndex
    has_shared: bool


class ValueOverrideVisibilityService:
    def __init__(self, *, workspace_id: str, user_id: str, sql: Optional[ForgeQueryPort] = None) -> None:
        if not workspace_id:
            raise ForgeError("workspace_id is required", status_code=400)
        if not user_id:
            raise ForgeError("user_id is required", status_code=400)
        self._workspace_id = workspace_id
        self._user_id = user_id
        self._sql = sql or ForgeMetaSQL()

    def get_index(self, *, include_expired: bool = False) -> ValueOverrideVisibilityResult:
        rows = self._fetch_visible_rows(include_expired=include_expired)

        buckets: Dict[ForgeSectionKey, List[ValueOverrideMeta]] = {
            "regions": [],
            "npiCategories": [],
            "serviceLines": [],
        }

        has_shared = False

        for r in rows:
            list_type = r.get("list_type")
            if list_type not in buckets:
                continue

            list_id = (r.get("list_id") or "").strip()
            list_name = (r.get("list_name") or "").strip()
            owner = (r.get("owner") or "").strip()
            user_id = (r.get("user_id") or "").strip() or None
            is_shared = _to_bool(r.get("is_shared"))

            if not list_id or not list_name or not (owner or user_id):
                continue

            buckets[list_type].append(
                ValueOverrideMeta(
                    list_id=list_id,
                    list_name=list_name,
                    owner=owner or (user_id or ""),
                    user_id=user_id,
                    is_shared=is_shared,
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    row_count=0,
                    expires_at=None,
                )
            )

            if is_shared:
                has_shared = True

        index = ValueOverrideListIndex(
            regions=buckets["regions"],
            npiCategories=buckets["npiCategories"],
            serviceLines=buckets["serviceLines"],
        )

        return ValueOverrideVisibilityResult(index=index, has_shared=has_shared)

    def _fetch_visible_rows(self, *, include_expired: bool) -> List[Dict[str, Any]]:
        del include_expired
        sql = """
        SELECT
          list_type AS list_type,
          list_id AS list_id,
          list_name AS list_name,
          user_name AS owner,
          user_id AS user_id,
          is_shared AS is_shared,
          created_at AS created_at,
          updated_at AS updated_at
        FROM crosswalk_list_meta
        WHERE workspace_id = :ws
          AND (user_id = :uid OR is_shared = 1)
        ORDER BY updated_at DESC, list_type ASC, list_name ASC
        """.strip()

        return self._sql.execute_query_mappings(
            sql,
            {"ws": self._workspace_id, "uid": self._user_id},
        )


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")
