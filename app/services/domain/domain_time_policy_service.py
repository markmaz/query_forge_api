from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort

_ALLOWED_CALENDAR_MODE = {"calendar", "fiscal", "school_year"}
_ALLOWED_WEEK_START = {"monday", "sunday"}
_ALLOWED_GRAIN = {"day", "week", "month", "quarter", "year"}
_SEMESTER_BUCKETS = ("spring", "fall", "year_round")


class DomainTimePolicyService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def get_policy(self, *, workspace_id: str, user_id: str, domain_id: int) -> Dict[str, Any]:
        row = self._load_row(workspace_id=workspace_id, user_id=user_id, domain_id=domain_id)
        return {
            "domain_id": int(row["domain_id"]),
            "domain_name": str(row.get("domain_name") or "").strip() or None,
            "has_policy": row.get("policy_id") is not None,
            "can_edit": bool(row.get("can_edit")),
            "policy": _policy_from_row(row),
        }

    def update_policy(
        self,
        *,
        workspace_id: str,
        user_id: str,
        domain_id: int,
        policy_payload: Any,
    ) -> Dict[str, Any]:
        row = self._load_row(workspace_id=workspace_id, user_id=user_id, domain_id=domain_id)
        if not bool(row.get("can_edit")):
            raise ForgeError("You do not have edit permission for this domain.", status_code=403)
        if not isinstance(policy_payload, Mapping):
            raise ForgeError("'policy' must be an object", status_code=400)

        base_policy = _policy_from_row(row)
        normalized = _normalize_policy_payload(payload=policy_payload, base=base_policy)

        params = {
            "workspace_id": str(workspace_id),
            "domain_id": int(domain_id),
            "calendar_mode": normalized["calendar_mode"],
            "fiscal_year_start_month": normalized["fiscal_year_start_month"],
            "school_year_start_month": normalized["school_year_start_month"],
            "school_year_end_month": normalized["school_year_end_month"],
            "timezone": normalized["timezone"],
            "week_start": normalized["week_start"],
            "default_time_concept_key": normalized["default_time_concept_key"],
            "allow_relative_ranges": 1 if normalized["allow_relative_ranges"] else 0,
            "default_grain": normalized["default_grain"],
            "prefer_time_object_over_filter": 1 if normalized["prefer_time_object_over_filter"] else 0,
            "strict_mode": 1 if normalized["strict_mode"] else 0,
            "relative_map": _json_dumps(normalized["relative_map"]),
            "semester_config": _json_dumps(normalized["semester"]),
            "notes": normalized["notes"],
        }

        with self._sql.transaction() as tx:
            if row.get("policy_id") is None:
                tx.execute_write(
                    """
                    INSERT INTO domain_time_policy (
                      workspace_id,
                      domain_id,
                      calendar_mode,
                      fiscal_year_start_month,
                      school_year_start_month,
                      school_year_end_month,
                      timezone,
                      week_start,
                      default_time_concept_key,
                      allow_relative_ranges,
                      default_grain,
                      prefer_time_object_over_filter,
                      strict_mode,
                      relative_map,
                      semester_config,
                      notes
                    ) VALUES (
                      :workspace_id,
                      :domain_id,
                      :calendar_mode,
                      :fiscal_year_start_month,
                      :school_year_start_month,
                      :school_year_end_month,
                      :timezone,
                      :week_start,
                      :default_time_concept_key,
                      :allow_relative_ranges,
                      :default_grain,
                      :prefer_time_object_over_filter,
                      :strict_mode,
                      :relative_map,
                      :semester_config,
                      :notes
                    )
                    """,
                    params,
                )
            else:
                tx.execute_write(
                    """
                    UPDATE domain_time_policy
                    SET calendar_mode = :calendar_mode,
                        fiscal_year_start_month = :fiscal_year_start_month,
                        school_year_start_month = :school_year_start_month,
                        school_year_end_month = :school_year_end_month,
                        timezone = :timezone,
                        week_start = :week_start,
                        default_time_concept_key = :default_time_concept_key,
                        allow_relative_ranges = :allow_relative_ranges,
                        default_grain = :default_grain,
                        prefer_time_object_over_filter = :prefer_time_object_over_filter,
                        strict_mode = :strict_mode,
                        relative_map = :relative_map,
                        semester_config = :semester_config,
                        notes = :notes,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :policy_id
                      AND workspace_id = :workspace_id
                      AND domain_id = :domain_id
                    """,
                    {**params, "policy_id": int(row["policy_id"])},
                )

        return self.get_policy(workspace_id=workspace_id, user_id=user_id, domain_id=domain_id)

    def _load_row(self, *, workspace_id: str, user_id: str, domain_id: int) -> Dict[str, Any]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              d.id AS domain_id,
              d.name AS domain_name,
              udm.can_edit,
              tp.id AS policy_id,
              tp.calendar_mode,
              tp.fiscal_year_start_month,
              tp.school_year_start_month,
              tp.school_year_end_month,
              tp.timezone,
              tp.week_start,
              tp.default_time_concept_key,
              tp.allow_relative_ranges,
              tp.default_grain,
              tp.prefer_time_object_over_filter,
              tp.strict_mode,
              tp.relative_map,
              tp.semester_config,
              tp.notes
            FROM domain d
            JOIN user_domain_mapping udm
              ON udm.domain_id = d.id
             AND udm.user_id = :user_id
             AND udm.can_read = 1
            LEFT JOIN domain_time_policy tp
              ON tp.workspace_id = d.workspace_id
             AND tp.domain_id = d.id
            WHERE d.workspace_id = :workspace_id
              AND d.id = :domain_id
              AND d.is_active = 1
            LIMIT 1
            """,
            {
                "workspace_id": str(workspace_id),
                "user_id": str(user_id),
                "domain_id": int(domain_id),
            },
        )
        if not rows:
            raise ForgeError("Domain not found or access denied", status_code=404)
        return dict(rows[0])


def _default_policy() -> Dict[str, Any]:
    return {
        "calendar_mode": "calendar",
        "fiscal_year_start_month": None,
        "school_year_start_month": None,
        "school_year_end_month": None,
        "timezone": None,
        "week_start": "monday",
        "default_time_concept_key": None,
        "allow_relative_ranges": True,
        "default_grain": None,
        "prefer_time_object_over_filter": True,
        "strict_mode": True,
        "relative_map": {},
        "semester": _default_semester_policy(),
        "notes": None,
    }


def _policy_from_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    out = _default_policy()
    if row.get("policy_id") is None:
        return out

    calendar_mode = str(row.get("calendar_mode") or "").strip().lower()
    if calendar_mode in _ALLOWED_CALENDAR_MODE:
        out["calendar_mode"] = calendar_mode

    fiscal_month = row.get("fiscal_year_start_month")
    if isinstance(fiscal_month, int) and 1 <= fiscal_month <= 12:
        out["fiscal_year_start_month"] = fiscal_month

    school_start = row.get("school_year_start_month")
    if isinstance(school_start, int) and 1 <= school_start <= 12:
        out["school_year_start_month"] = school_start

    school_end = row.get("school_year_end_month")
    if isinstance(school_end, int) and 1 <= school_end <= 12:
        out["school_year_end_month"] = school_end

    timezone = str(row.get("timezone") or "").strip()
    out["timezone"] = timezone or None

    week_start = str(row.get("week_start") or "").strip().lower()
    if week_start in _ALLOWED_WEEK_START:
        out["week_start"] = week_start

    default_key = str(row.get("default_time_concept_key") or "").strip()
    out["default_time_concept_key"] = default_key or None

    out["allow_relative_ranges"] = bool(row.get("allow_relative_ranges", 1))

    default_grain = str(row.get("default_grain") or "").strip().lower()
    out["default_grain"] = default_grain if default_grain in _ALLOWED_GRAIN else None

    out["prefer_time_object_over_filter"] = bool(row.get("prefer_time_object_over_filter", 1))
    out["strict_mode"] = bool(row.get("strict_mode", 1))

    rel = _parse_json(row.get("relative_map"))
    out["relative_map"] = rel if isinstance(rel, dict) else {}

    semester = _parse_json(row.get("semester_config"))
    out["semester"] = _normalize_semester_policy_payload(semester, base=out["semester"], require_complete=False)

    notes = str(row.get("notes") or "").strip()
    out["notes"] = notes or None
    return out


def _normalize_policy_payload(*, payload: Mapping[str, Any], base: Mapping[str, Any]) -> Dict[str, Any]:
    out = dict(base)

    if "calendar_mode" in payload:
        mode = str(payload.get("calendar_mode") or "").strip().lower()
        if mode not in _ALLOWED_CALENDAR_MODE:
            raise ForgeError("policy.calendar_mode must be 'calendar', 'fiscal', or 'school_year'", status_code=400)
        out["calendar_mode"] = mode

    if "fiscal_year_start_month" in payload:
        fiscal = payload.get("fiscal_year_start_month")
        if fiscal is None or str(fiscal).strip() == "":
            out["fiscal_year_start_month"] = None
        elif isinstance(fiscal, int) and 1 <= fiscal <= 12:
            out["fiscal_year_start_month"] = fiscal
        else:
            raise ForgeError("policy.fiscal_year_start_month must be an integer between 1 and 12", status_code=400)

    if "school_year_start_month" in payload:
        school_start = payload.get("school_year_start_month")
        if school_start is None or str(school_start).strip() == "":
            out["school_year_start_month"] = None
        elif isinstance(school_start, int) and 1 <= school_start <= 12:
            out["school_year_start_month"] = school_start
        else:
            raise ForgeError("policy.school_year_start_month must be an integer between 1 and 12", status_code=400)

    if "school_year_end_month" in payload:
        school_end = payload.get("school_year_end_month")
        if school_end is None or str(school_end).strip() == "":
            out["school_year_end_month"] = None
        elif isinstance(school_end, int) and 1 <= school_end <= 12:
            out["school_year_end_month"] = school_end
        else:
            raise ForgeError("policy.school_year_end_month must be an integer between 1 and 12", status_code=400)

    if "timezone" in payload:
        tz = str(payload.get("timezone") or "").strip()
        if tz and len(tz) > 64:
            raise ForgeError("policy.timezone must be 64 chars or fewer", status_code=400)
        out["timezone"] = tz or None

    if "week_start" in payload:
        week = str(payload.get("week_start") or "").strip().lower()
        if week not in _ALLOWED_WEEK_START:
            raise ForgeError("policy.week_start must be 'monday' or 'sunday'", status_code=400)
        out["week_start"] = week

    if "default_time_concept_key" in payload:
        key = str(payload.get("default_time_concept_key") or "").strip()
        out["default_time_concept_key"] = key or None

    if "allow_relative_ranges" in payload:
        allow = payload.get("allow_relative_ranges")
        if not isinstance(allow, bool):
            raise ForgeError("policy.allow_relative_ranges must be a boolean", status_code=400)
        out["allow_relative_ranges"] = allow

    if "default_grain" in payload:
        grain_raw = payload.get("default_grain")
        grain = str(grain_raw or "").strip().lower()
        if grain_raw is None or grain == "":
            out["default_grain"] = None
        elif grain in _ALLOWED_GRAIN:
            out["default_grain"] = grain
        else:
            raise ForgeError("policy.default_grain must be one of day|week|month|quarter|year|null", status_code=400)

    if "prefer_time_object_over_filter" in payload:
        prefer = payload.get("prefer_time_object_over_filter")
        if not isinstance(prefer, bool):
            raise ForgeError("policy.prefer_time_object_over_filter must be a boolean", status_code=400)
        out["prefer_time_object_over_filter"] = prefer

    if "strict_mode" in payload:
        strict = payload.get("strict_mode")
        if not isinstance(strict, bool):
            raise ForgeError("policy.strict_mode must be a boolean", status_code=400)
        out["strict_mode"] = strict

    if "relative_map" in payload:
        rel = payload.get("relative_map")
        if rel is None:
            out["relative_map"] = {}
        elif isinstance(rel, Mapping):
            normalized_rel: Dict[str, str] = {}
            for key, val in rel.items():
                k = str(key or "").strip()
                v = str(val or "").strip()
                if not k or not v:
                    raise ForgeError("policy.relative_map keys and values must be non-empty strings", status_code=400)
                normalized_rel[k] = v
            out["relative_map"] = normalized_rel
        else:
            raise ForgeError("policy.relative_map must be an object", status_code=400)

    if "semester" in payload:
        out["semester"] = _normalize_semester_policy_payload(payload.get("semester"), base=out["semester"], require_complete=False)

    if "notes" in payload:
        notes = str(payload.get("notes") or "").strip()
        out["notes"] = notes or None

    return out


def _parse_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="ignore")
    text = str(value or "").strip()
    if text == "":
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _json_dumps(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _default_semester_policy() -> Dict[str, Any]:
    return {
        "labels": {
            "spring": "Spring",
            "fall": "Fall",
            "year_round": "Year Round",
        },
        "month_ranges": {
            "spring": [1, 5],
            "fall": [8, 12],
            "year_round": [6, 7],
        },
        "indicator_columns": {},
    }


def _normalize_semester_policy_payload(
    value: Any,
    *,
    base: Optional[Mapping[str, Any]] = None,
    require_complete: bool = False,
) -> Dict[str, Any]:
    out = {
        "labels": dict((base or _default_semester_policy()).get("labels") or _default_semester_policy()["labels"]),
        "month_ranges": dict((base or _default_semester_policy()).get("month_ranges") or _default_semester_policy()["month_ranges"]),
        "indicator_columns": dict((base or _default_semester_policy()).get("indicator_columns") or {}),
    }
    if value is None:
        return out
    if not isinstance(value, Mapping):
        raise ForgeError("policy.semester must be an object", status_code=400)

    if "labels" in value:
        labels = value.get("labels")
        if labels is None:
            out["labels"] = dict(_default_semester_policy()["labels"])
        elif isinstance(labels, Mapping):
            normalized_labels: Dict[str, str] = {}
            for bucket in _SEMESTER_BUCKETS:
                raw = labels.get(bucket)
                text = str(raw or "").strip()
                if not text:
                    if require_complete:
                        raise ForgeError(f"policy.semester.labels.{bucket} is required", status_code=400)
                    text = str(out["labels"].get(bucket) or "").strip()
                if not text:
                    raise ForgeError(f"policy.semester.labels.{bucket} must be a non-empty string", status_code=400)
                normalized_labels[bucket] = text
            out["labels"] = normalized_labels
        else:
            raise ForgeError("policy.semester.labels must be an object", status_code=400)

    if "month_ranges" in value:
        month_ranges = value.get("month_ranges")
        if month_ranges is None:
            out["month_ranges"] = dict(_default_semester_policy()["month_ranges"])
        elif isinstance(month_ranges, Mapping):
            normalized_ranges: Dict[str, list[int]] = {}
            for bucket in _SEMESTER_BUCKETS:
                raw = month_ranges.get(bucket)
                if raw is None:
                    if require_complete:
                        raise ForgeError(f"policy.semester.month_ranges.{bucket} is required", status_code=400)
                    raw = out["month_ranges"].get(bucket)
                if not isinstance(raw, (list, tuple)) or len(raw) != 2:
                    raise ForgeError(
                        f"policy.semester.month_ranges.{bucket} must be a two-item month range",
                        status_code=400,
                    )
                start = _coerce_month(raw[0], field=f"policy.semester.month_ranges.{bucket}[0]")
                end = _coerce_month(raw[1], field=f"policy.semester.month_ranges.{bucket}[1]")
                normalized_ranges[bucket] = [start, end]
            out["month_ranges"] = normalized_ranges
        else:
            raise ForgeError("policy.semester.month_ranges must be an object", status_code=400)

    if "indicator_columns" in value:
        indicator_columns = value.get("indicator_columns")
        if indicator_columns is None:
            out["indicator_columns"] = {}
        elif isinstance(indicator_columns, Mapping):
            normalized_columns: Dict[str, str] = {}
            for bucket, raw in indicator_columns.items():
                bucket_key = str(bucket or "").strip().lower()
                if bucket_key not in _SEMESTER_BUCKETS:
                    raise ForgeError(
                        "policy.semester.indicator_columns keys must be spring|fall|year_round",
                        status_code=400,
                    )
                column_key = str(raw or "").strip()
                if not column_key:
                    raise ForgeError(
                        f"policy.semester.indicator_columns.{bucket_key} must be a non-empty string",
                        status_code=400,
                    )
                normalized_columns[bucket_key] = column_key
            out["indicator_columns"] = normalized_columns
        else:
            raise ForgeError("policy.semester.indicator_columns must be an object", status_code=400)

    return out


def _coerce_month(value: Any, *, field: str) -> int:
    if not isinstance(value, int) or value < 1 or value > 12:
        raise ForgeError(f"{field} must be an integer between 1 and 12", status_code=400)
    return value


__all__ = ["DomainTimePolicyService"]
