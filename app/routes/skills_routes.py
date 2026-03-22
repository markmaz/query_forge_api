from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from app.skills.schedule_utils import get_scheduler_health, next_n_runs, validate_cron
from typing import Any, Dict, Iterable

from flask import g, request
from flask_restx import Namespace, fields

from app.decorators.security import token_required
from app.decorators.rbac import require_access
from app.decorators.ownership import require_ownership
from app.exceptions.forge_error import ForgeError
from app.routes.forge_resource import ForgeResource
from app.routes.request_helpers import extract_workspace_id, int_arg, require_user_id

logger = logging.getLogger(__name__)

skills_ns = Namespace("skills", description="QueryForge Skills")

_SKILL_META_KEY = "_qf_skill"
_FRONTEND_TO_BACKEND_SKILL_TYPE = {
    "email_report": "email_delivery",
    "slack_delivery": "webhook_delivery",
}
_BACKEND_TO_FRONTEND_SKILL_TYPE = {
    "email_delivery": "email_report",
}
_DAY_OF_WEEK_TO_CRON = {
    "sunday": "0",
    "monday": "1",
    "tuesday": "2",
    "wednesday": "3",
    "thursday": "4",
    "friday": "5",
    "saturday": "6",
}


def _serialize_row(row: dict) -> dict:
    import json as _json

    out = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif k == "config_json" and isinstance(v, str):
            try:
                out[k] = _json.loads(v)
            except Exception:
                out[k] = v
        else:
            out[k] = v
    return out


def _json_object(value: Any) -> dict[str, Any]:
    import json as _json

    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = _json.loads(value)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _to_list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _split_csv_or_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _destination_id_from_config(config: dict[str, Any]) -> int | None:
    raw = config.get("destination_id")
    if raw in (None, "", 0, "0"):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _frontend_skill_type(raw_skill_type: str, *, meta: dict[str, Any], actions: list[dict[str, Any]]) -> str:
    explicit = str(meta.get("skill_type") or "").strip()
    if explicit:
        return explicit
    backend = str(raw_skill_type or "").strip()
    if backend == "webhook_delivery":
        for action in actions:
            if str(action.get("type") or "").strip() == "slack_delivery":
                return "slack_delivery"
    return _BACKEND_TO_FRONTEND_SKILL_TYPE.get(backend, backend)


def _backend_skill_type(raw_skill_type: str) -> str:
    normalized = str(raw_skill_type or "").strip()
    return _FRONTEND_TO_BACKEND_SKILL_TYPE.get(normalized, normalized)


def _status_from_row(*, meta: dict[str, Any], row: dict[str, Any]) -> str:
    explicit = str(meta.get("status") or "").strip().lower()
    if explicit in {"draft", "active", "paused", "error"}:
        return explicit
    return "active" if int(row.get("is_active") or 0) else "draft"


def _default_trigger() -> dict[str, Any]:
    return {
        "id": "trigger_schedule",
        "kind": "trigger",
        "type": "schedule",
        "label": "Schedule",
        "enabled": True,
        "config": {"frequency": "daily", "time": "08:00", "timezone": "UTC"},
    }


def _workflow_from_parts(
    trigger: dict[str, Any] | None,
    conditions: list[dict[str, Any]],
    actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    workflow: list[dict[str, Any]] = []
    if trigger:
        workflow.append(trigger)
    workflow.extend(conditions)
    workflow.extend(actions)
    return workflow


def _extract_meta(config_json: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    config = _json_object(config_json)
    meta = _json_object(config.get(_SKILL_META_KEY))
    runtime_config = {k: v for k, v in config.items() if k != _SKILL_META_KEY}
    return runtime_config, meta


def _derive_channels_from_actions(actions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    channels: list[dict[str, Any]] = []
    for action in actions:
        action_type = str(action.get("type") or "").strip()
        cfg = _json_object(action.get("config"))
        destination_id = _destination_id_from_config(cfg)
        if action_type == "email_report":
            if destination_id is not None:
                channels.append({"type": "email", "destination_id": destination_id})
                continue
            recipients = _split_csv_or_list(cfg.get("recipients"))
            if recipients:
                channels.append({"type": "email", "recipients": recipients})
        elif action_type == "slack_delivery":
            if destination_id is not None:
                channels.append({"type": "slack", "destination_id": destination_id})
                continue
            webhook_url = str(cfg.get("webhook_url") or "").strip()
            if webhook_url:
                channels.append({"type": "slack", "webhook_url": webhook_url})
        elif action_type == "webhook_delivery":
            channel_type = str(cfg.get("channel_type") or "slack").strip().lower() or "slack"
            if channel_type not in {"slack", "teams", "webhook"}:
                channel_type = "slack"
            if destination_id is not None:
                channels.append({"type": channel_type, "destination_id": destination_id})
                continue
            webhook_url = str(cfg.get("webhook_url") or cfg.get("endpoint_url") or cfg.get("url") or "").strip()
            if webhook_url:
                channel_config: dict[str, Any] = {"type": channel_type}
                if channel_type == "webhook":
                    channel_config["url"] = webhook_url
                    channel_config["method"] = str(cfg.get("method") or "POST").strip().upper() or "POST"
                    headers = _json_object(cfg.get("headers_json") or cfg.get("headers"))
                    if headers:
                        channel_config["headers"] = headers
                    auth_token = str(cfg.get("auth_token") or "").strip()
                    if auth_token:
                        channel_config["auth_token"] = auth_token
                else:
                    channel_config["webhook_url"] = webhook_url
                channels.append(channel_config)
    return channels


def _runtime_config_from_meta(*, backend_skill_type: str, meta: dict[str, Any], existing_runtime: dict[str, Any]) -> dict[str, Any]:
    actions = _to_list_of_dicts(meta.get("actions"))
    conditions = _to_list_of_dicts(meta.get("conditions"))
    trigger = _json_object(meta.get("trigger"))
    description = str(meta.get("description") or "").strip()

    if backend_skill_type == "email_delivery":
        action = next((a for a in actions if str(a.get("type") or "") == "email_report"), actions[0] if actions else {})
        cfg = _json_object(action.get("config"))
        destination_id = _destination_id_from_config(cfg)
        return {
            **existing_runtime,
            "destination_id": destination_id,
            "recipients": _split_csv_or_list(cfg.get("recipients")),
            "subject": str(cfg.get("subject") or "QueryForge report"),
            "reply_to": cfg.get("reply_to") or None,
            "include_summary": bool(cfg.get("include_ai_summary", True)),
        }

    if backend_skill_type == "ai_summary_digest":
        action = next((a for a in actions if str(a.get("type") or "") == "ai_summary_digest"), actions[0] if actions else {})
        cfg = _json_object(action.get("config"))
        destination_id = _destination_id_from_config(cfg)
        return {
            **existing_runtime,
            "destination_id": destination_id,
            "recipients": _split_csv_or_list(cfg.get("recipients")),
            "subject": str(cfg.get("subject") or "{{query_name}} Digest"),
            "prompt_hint": str(cfg.get("prompt_template") or "").strip(),
            "include_comparison": bool(cfg.get("include_comparison", True)),
            "include_appendix": bool(cfg.get("include_appendix", False)),
            "max_rows": int(cfg.get("max_rows") or 100),
            "include_query_link": bool(cfg.get("include_query_link", True)),
        }

    if backend_skill_type == "webhook_delivery":
        action = next(
            (
                a for a in actions
                if str(a.get("type") or "") in {"webhook_delivery", "slack_delivery"}
            ),
            actions[0] if actions else {},
        )
        cfg = _json_object(action.get("config"))
        channel_type = str(cfg.get("channel_type") or ("slack" if str(action.get("type") or "") == "slack_delivery" else "slack")).strip().lower()
        if channel_type not in {"slack", "teams", "webhook"}:
            channel_type = "slack"
        destination_id = _destination_id_from_config(cfg)
        return {
            **existing_runtime,
            "channel_type": channel_type,
            "channels": _derive_channels_from_actions(actions),
            "destination_id": destination_id,
            "webhook_url": str(cfg.get("webhook_url") or cfg.get("endpoint_url") or cfg.get("url") or "").strip(),
            "url": str(cfg.get("url") or cfg.get("endpoint_url") or cfg.get("webhook_url") or "").strip(),
            "method": str(cfg.get("method") or "POST").strip().upper() or "POST",
            "headers": _json_object(cfg.get("headers_json") or cfg.get("headers")),
            "auth_token": str(cfg.get("auth_token") or "").strip() or None,
            "message": str(cfg.get("message_template") or cfg.get("message") or description).strip(),
            "format": "table" if bool(cfg.get("include_table_preview")) else "summary",
            "max_rows": int(cfg.get("max_rows") or 10),
            "send_if_empty": bool(cfg.get("send_if_empty", False)),
            "severity": str(cfg.get("severity") or "info"),
        }

    if backend_skill_type == "threshold_alert":
        runtime_conditions: list[dict[str, Any]] = []
        for condition in conditions:
            cond_type = str(condition.get("type") or "").strip()
            cfg = _json_object(condition.get("config"))
            if cond_type in {"metric_threshold", "row_count_threshold"}:
                runtime_conditions.append(
                    {
                        "type": "row_count",
                        "operator": str(cfg.get("operator") or ">"),
                        "value": float(cfg.get("value") or 0),
                    }
                )
            elif cond_type == "custom_rule":
                expression = str(cfg.get("expression") or "").strip()
                if expression:
                    runtime_conditions.append({"type": "ai_expectation", "prompt": expression})
        if not runtime_conditions and trigger and str(trigger.get("type") or "") == "threshold_alert":
            trigger_cfg = _json_object(trigger.get("config"))
            runtime_conditions.append(
                {
                    "type": "row_count",
                    "operator": str(trigger_cfg.get("operator") or ">"),
                    "value": float(trigger_cfg.get("threshold") or 0),
                }
            )
        return {
            **existing_runtime,
            "conditions": runtime_conditions,
            "condition_mode": str(meta.get("condition_mode") or "any"),
            "alert_mode": str(meta.get("alert_mode") or "on_change"),
            "resolution_mode": str(meta.get("resolution_mode") or "auto"),
            "channels": _derive_channels_from_actions(actions),
            "severity": str(meta.get("severity") or "warning"),
            "message": description,
        }

    if backend_skill_type == "data_freshness_check":
        runtime_checks: list[dict[str, Any]] = []
        if trigger and str(trigger.get("type") or "") == "data_freshness_check":
            trigger_cfg = _json_object(trigger.get("config"))
            runtime_checks.append(
                {
                    "type": "timestamp_stale" if str(trigger_cfg.get("freshness_column") or "").strip() else "no_new_rows",
                    "column": str(trigger_cfg.get("freshness_column") or "").strip() or None,
                    "window_mode": "fixed",
                    "fixed_hours": max(int(trigger_cfg.get("interval_value") or 1) * 24, 1),
                }
            )
        for condition in conditions:
            if str(condition.get("type") or "").strip() == "no_new_rows":
                cfg = _json_object(condition.get("config"))
                runtime_checks.append(
                    {
                        "type": "no_new_rows",
                        "window_mode": "fixed",
                        "fixed_hours": max(int(cfg.get("interval_value") or 1) * 24, 1),
                    }
                )
        return {
            **existing_runtime,
            "checks": runtime_checks,
            "check_mode": str(meta.get("check_mode") or "any"),
            "alert_mode": str(meta.get("alert_mode") or "on_change"),
            "channels": _derive_channels_from_actions(actions),
            "severity": str(meta.get("severity") or "warning"),
            "message": description,
        }

    return existing_runtime


def _config_from_request(body: dict[str, Any], *, existing_row: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, str | None, int | None]:
    existing_runtime: dict[str, Any] = {}
    existing_meta: dict[str, Any] = {}
    existing_is_active = None
    if existing_row:
        existing_runtime, existing_meta = _extract_meta(existing_row.get("config_json"))
        existing_is_active = int(existing_row.get("is_active") or 0)

    explicit_config = None
    if "config_json" in body or "config" in body:
        explicit_config = _json_object(body.get("config_json") or body.get("config"))

    meta = dict(existing_meta)
    if "description" in body:
        meta["description"] = body.get("description")
    if "query_name" in body:
        meta["query_name"] = body.get("query_name")
    if "condition_mode" in body:
        meta["condition_mode"] = body.get("condition_mode")
    if "check_mode" in body:
        meta["check_mode"] = body.get("check_mode")
    if "alert_mode" in body:
        meta["alert_mode"] = body.get("alert_mode")
    if "resolution_mode" in body:
        meta["resolution_mode"] = body.get("resolution_mode")
    if "severity" in body:
        meta["severity"] = body.get("severity")

    input_skill_type = str(body.get("skill_type") or meta.get("skill_type") or "").strip()
    backend_type = _backend_skill_type(input_skill_type) if input_skill_type else None
    if input_skill_type:
        meta["skill_type"] = input_skill_type

    for key in ("trigger", "workflow"):
        if key in body:
            meta[key] = body.get(key)
    for key in ("conditions", "actions"):
        if key in body:
            meta[key] = body.get(key) or []

    if "trigger" in meta or "conditions" in meta or "actions" in meta:
        trigger = _json_object(meta.get("trigger")) or _default_trigger()
        conditions = _to_list_of_dicts(meta.get("conditions"))
        actions = _to_list_of_dicts(meta.get("actions"))
        meta["trigger"] = trigger
        meta["conditions"] = conditions
        meta["actions"] = actions
        meta["workflow"] = _workflow_from_parts(trigger, conditions, actions)

    if "status" in body:
        meta["status"] = body.get("status")
    status = str(meta.get("status") or "").strip().lower() or None
    is_active = existing_is_active
    if status:
        is_active = 1 if status == "active" else 0
    elif "is_active" in body and body.get("is_active") is not None:
        is_active = int(body.get("is_active"))

    if explicit_config is None and not meta and existing_row is None:
        return None, backend_type, is_active

    runtime = explicit_config if explicit_config is not None else dict(existing_runtime)
    if backend_type:
        runtime = _runtime_config_from_meta(
            backend_skill_type=backend_type,
            meta=meta,
            existing_runtime=runtime,
        )

    config_payload = dict(runtime)
    if meta:
        config_payload[_SKILL_META_KEY] = meta
    return config_payload or None, backend_type, is_active


def _normalize_skill_row(row: dict[str, Any]) -> dict[str, Any]:
    runtime_config, meta = _extract_meta(row.get("config_json"))
    trigger = _json_object(meta.get("trigger")) or _default_trigger()
    conditions = _to_list_of_dicts(meta.get("conditions"))
    actions = _to_list_of_dicts(meta.get("actions"))
    workflow = _to_list_of_dicts(meta.get("workflow")) or _workflow_from_parts(trigger, conditions, actions)
    frontend_skill_type = _frontend_skill_type(str(row.get("skill_type") or ""), meta=meta, actions=actions)

    out = _serialize_row(dict(row))
    out["config_json"] = runtime_config
    out["description"] = meta.get("description")
    out["query_name"] = meta.get("query_name")
    out["status"] = _status_from_row(meta=meta, row=row)
    out["skill_type"] = frontend_skill_type
    out["trigger"] = trigger
    out["conditions"] = conditions
    out["actions"] = actions
    out["workflow"] = workflow
    return out


def _normalize_skill_run_row(row: dict[str, Any]) -> dict[str, Any]:
    out = _serialize_row(dict(row))
    result = _json_object(out.get("result_json"))
    data = _json_object(result.get("data"))
    message = str(result.get("message") or "").strip()
    if out.get("status") == "success" and data.get("skipped") is True:
        out["status"] = "skipped"
    if message:
        out["message"] = message
    events: list[dict[str, Any]] = []
    created_at = out.get("created_at")
    started_at = out.get("started_at")
    finished_at = out.get("finished_at")
    status = str(out.get("status") or "pending")
    final_message = str(out.get("message") or "").strip()

    if created_at:
        events.append(
            {
                "id": f"{out.get('id')}:queued",
                "status": "pending",
                "timestamp": created_at,
                "message": "Run queued.",
            }
        )
    if started_at:
        events.append(
            {
                "id": f"{out.get('id')}:started",
                "status": "info",
                "timestamp": started_at,
                "message": "Execution started.",
            }
        )
    if finished_at or final_message:
        events.append(
            {
                "id": f"{out.get('id')}:finished",
                "status": status,
                "timestamp": finished_at or started_at or created_at,
                "message": final_message or "Run complete.",
            }
        )

    out["events"] = events
    return out


def _time_parts(value: Any) -> tuple[int, int]:
    raw = str(value or "08:00").strip() or "08:00"
    try:
        hour_str, minute_str = raw.split(":", 1)
        hour = max(0, min(int(hour_str), 23))
        minute = max(0, min(int(minute_str), 59))
        return hour, minute
    except Exception:
        return 8, 0


def _cron_expr_from_trigger(trigger: dict[str, Any]) -> str:
    cfg = _json_object(trigger.get("config"))
    frequency = str(cfg.get("frequency") or "daily").strip().lower()
    hour, minute = _time_parts(cfg.get("time"))
    if frequency == "hourly":
        return f"{minute} * * * *"
    if frequency == "weekly":
        day = _DAY_OF_WEEK_TO_CRON.get(str(cfg.get("day_of_week") or "monday").strip().lower(), "1")
        return f"{minute} {hour} * * {day}"
    if frequency == "monthly":
        return f"{minute} {hour} 1 * *"
    return f"{minute} {hour} * * *"


def _cron_expr_from_validate_request(body: dict[str, Any]) -> tuple[str, str]:
    timezone_name = str(body.get("timezone") or "UTC").strip() or "UTC"
    expression = str(body.get("cron_expression") or "").strip()
    if expression:
        return expression, timezone_name

    trigger = _json_object(body.get("trigger"))
    if trigger:
        cfg = _json_object(trigger.get("config"))
        if not body.get("timezone") and cfg.get("timezone"):
            timezone_name = str(cfg.get("timezone") or "UTC").strip() or "UTC"
        return _cron_expr_from_trigger(trigger), timezone_name

    raise ForgeError("cron_expression or trigger is required", status_code=400)


def _normalize_next_run_at(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        dt = datetime.fromisoformat(raw)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _resolve_next_run_at(*, cron_expr: str, timezone_name: str, next_run_at_raw: Any = None) -> datetime | None:
    explicit = _normalize_next_run_at(next_run_at_raw)
    if explicit is not None:
        return explicit
    upcoming = next_n_runs(cron_expr, timezone_name, n=1)
    if not upcoming:
        return None
    return _normalize_next_run_at(upcoming[0])


def _schedule_payload_from_meta(*, meta: dict[str, Any], skill_is_active: int) -> dict[str, Any] | None:
    trigger = _json_object(meta.get("trigger"))
    if str(trigger.get("type") or "").strip() != "schedule":
        return None
    cfg = _json_object(trigger.get("config"))
    is_trigger_active = bool(trigger.get("enabled", True)) and bool(cfg.get("active", True))
    timezone_name = str(cfg.get("timezone") or "UTC").strip() or "UTC"
    cron_expr = _cron_expr_from_trigger(trigger)
    errors = validate_cron(cron_expr, timezone_name)
    if errors:
        raise ForgeError("; ".join(errors), status_code=400)
    is_active = 1 if (skill_is_active and is_trigger_active) else 0
    return {
        "cron_expr": cron_expr,
        "timezone": timezone_name,
        "next_run_at": _resolve_next_run_at(cron_expr=cron_expr, timezone_name=timezone_name) if is_active else None,
        "is_active": is_active,
        "trigger": trigger,
    }


def _latest_skill_schedule(sql: Any, *, skill_id: str, workspace_id: str) -> dict[str, Any] | None:
    rows = sql.execute_query_mappings(
        """
        SELECT id, skill_id, workspace_id, cron_expr, timezone, next_run_at,
               last_run_at, is_active, catch_up, created_at, updated_at
        FROM skill_schedules
        WHERE skill_id = :skill_id AND workspace_id = :ws
        ORDER BY created_at DESC
        LIMIT 1
        """,
        {"skill_id": skill_id, "ws": workspace_id},
    )
    return dict(rows[0]) if rows else None


def _serialize_schedule_row(row: dict[str, Any]) -> dict[str, Any]:
    out = _serialize_row(dict(row))
    out["upcoming"] = next_n_runs(
        str(row.get("cron_expr") or ""),
        str(row.get("timezone") or "UTC"),
        n=5,
    ) if str(row.get("is_active") or 0) == "1" or int(row.get("is_active") or 0) == 1 else []
    return out


def _sync_skill_schedule(
    sql: Any,
    *,
    skill_id: str,
    workspace_id: str,
    config_json: Any,
    skill_is_active: int,
) -> dict[str, Any] | None:
    _, meta = _extract_meta(config_json)
    schedule_payload = _schedule_payload_from_meta(meta=meta, skill_is_active=skill_is_active) if meta else None
    existing = _latest_skill_schedule(sql, skill_id=skill_id, workspace_id=workspace_id)

    if schedule_payload is None:
        if existing:
            sql.execute_write(
                "UPDATE skill_schedules SET is_active = 0, next_run_at = NULL, updated_at = :updated_at WHERE id = :id",
                {"id": existing["id"], "updated_at": datetime.now(timezone.utc)},
            )
            existing["is_active"] = 0
            existing["next_run_at"] = None
            existing["updated_at"] = datetime.now(timezone.utc)
            return existing
        return None

    if existing:
        sql.execute_write(
            """
            UPDATE skill_schedules
            SET cron_expr = :cron_expr,
                timezone = :timezone,
                next_run_at = :next_run_at,
                is_active = :is_active,
                updated_at = :updated_at
            WHERE id = :id
            """,
            {
                "id": existing["id"],
                "cron_expr": schedule_payload["cron_expr"],
                "timezone": schedule_payload["timezone"],
                "next_run_at": schedule_payload["next_run_at"],
                "is_active": schedule_payload["is_active"],
                "updated_at": datetime.now(timezone.utc),
            },
        )
        existing.update(
            cron_expr=schedule_payload["cron_expr"],
            timezone=schedule_payload["timezone"],
            next_run_at=schedule_payload["next_run_at"],
            is_active=schedule_payload["is_active"],
            updated_at=datetime.now(timezone.utc),
        )
        return existing

    schedule_id = str(uuid.uuid4())
    sql.execute_write(
        """
        INSERT INTO skill_schedules (
            id, skill_id, workspace_id, cron_expr, timezone, next_run_at, is_active, created_at
        )
        VALUES (
            :id, :skill_id, :workspace_id, :cron_expr, :timezone, :next_run_at, :is_active, CURRENT_TIMESTAMP
        )
        """,
        {
            "id": schedule_id,
            "skill_id": skill_id,
            "workspace_id": workspace_id,
            "cron_expr": schedule_payload["cron_expr"],
            "timezone": schedule_payload["timezone"],
            "next_run_at": schedule_payload["next_run_at"],
            "is_active": schedule_payload["is_active"],
        },
    )
    return _latest_skill_schedule(sql, skill_id=skill_id, workspace_id=workspace_id)

_skill_create_model = skills_ns.model(
    "SkillCreate",
    {
        "name": fields.String(required=True),
        "skill_type": fields.String(required=True),
        "query_id": fields.String(required=False),
        "config_json": fields.Raw(required=False),
        "is_active": fields.Integer(required=False, default=1),
    },
)

_skill_update_model = skills_ns.model(
    "SkillUpdate",
    {
        "name": fields.String(required=False),
        "skill_type": fields.String(required=False),
        "query_id": fields.String(required=False),
        "config_json": fields.Raw(required=False),
        "is_active": fields.Integer(required=False),
    },
)

_schedule_create_model = skills_ns.model(
    "SkillScheduleCreate",
    {
        "cron_expr": fields.String(required=True),
        "timezone": fields.String(required=False, default="UTC"),
        "next_run_at": fields.String(required=False),
        "is_active": fields.Integer(required=False, default=1),
    },
)

_schedule_update_model = skills_ns.model(
    "SkillScheduleUpdate",
    {
        "cron_expr": fields.String(required=False),
        "timezone": fields.String(required=False),
        "next_run_at": fields.String(required=False),
        "is_active": fields.Integer(required=False),
    },
)

_execute_response_model = skills_ns.model(
    "SkillExecuteResponse",
    {
        "execution_id": fields.String(required=True),
        "job_id": fields.String(required=True),
        "status": fields.String(required=True),
    },
)


@skills_ns.route("")
class SkillList(ForgeResource):
    @token_required
    @require_access("skills")
    @skills_ns.doc(params={"page": "Page number (default 1)", "page_size": "Page size (default 20, max 100)"})
    def get(self):
        try:
            workspace_id = extract_workspace_id()
            search = str(request.args.get("q") or "").strip().lower()
            status_filter = str(request.args.get("status") or "").strip().lower()
            skill_type_filter = str(request.args.get("skill_type") or "").strip()
            page = int_arg("page", 1)
            page_size = min(int_arg("page_size", 20), 100)

            from app.adapters.mysql_sql_executor import ForgeMetaSQL

            sql = ForgeMetaSQL()
            rows = sql.execute_query_mappings(
                """
                SELECT qs.id, qs.workspace_id, qs.name, qs.skill_type, qs.query_id, qs.config_json,
                       qs.is_active, qs.created_by, qs.created_at, qs.updated_at,
                       MAX(se.started_at) AS last_run_at,
                       COUNT(se.id) AS run_count
                FROM query_skills
                qs
                LEFT JOIN skill_executions se
                  ON se.skill_id = qs.id
                 AND se.workspace_id = qs.workspace_id
                WHERE qs.workspace_id = :ws
                GROUP BY qs.id, qs.workspace_id, qs.name, qs.skill_type, qs.query_id, qs.config_json,
                         qs.is_active, qs.created_by, qs.created_at, qs.updated_at
                ORDER BY qs.created_at DESC
                """,
                {"ws": workspace_id},
            )
            normalized = [_normalize_skill_row(dict(r)) for r in rows]
            if search:
                normalized = [
                    row for row in normalized
                    if search in str(row.get("name") or "").lower()
                    or search in str(row.get("description") or "").lower()
                ]
            if status_filter:
                normalized = [row for row in normalized if str(row.get("status") or "").lower() == status_filter]
            if skill_type_filter:
                normalized = [row for row in normalized if str(row.get("skill_type") or "") == skill_type_filter]

            total = len(normalized)
            offset = (page - 1) * page_size
            page_rows = normalized[offset: offset + page_size]
            return {
                "data": page_rows,
                "page": page,
                "page_size": page_size,
                "total": total,
            }, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skills list failed")
            return {"error": "skills list failed"}, 500

    @token_required
    @require_access("skills", role="admin")
    @skills_ns.expect(_skill_create_model, validate=False)
    def post(self):
        try:
            workspace_id = extract_workspace_id()
            user_id = require_user_id()
            body: Dict[str, Any] = request.get_json(silent=True) or {}

            name = str(body.get("name") or "").strip()
            skill_type = str(body.get("skill_type") or "").strip()
            if not name:
                raise ForgeError("name is required", status_code=400)
            if not skill_type:
                raise ForgeError("skill_type is required", status_code=400)

            query_id = body.get("query_id") or None
            config_json, backend_skill_type, is_active = _config_from_request(body)
            if is_active is None:
                is_active = int(body.get("is_active", 1))
            skill_id = str(uuid.uuid4())

            from app.adapters.mysql_sql_executor import ForgeMetaSQL
            import json as _json

            sql = ForgeMetaSQL()
            config_str = _json.dumps(config_json) if config_json is not None else None
            sql.execute_write(
                """
                INSERT INTO query_skills (id, workspace_id, name, skill_type, query_id, config_json, is_active, created_by, created_at)
                VALUES (:id, :ws, :name, :skill_type, :query_id, :config_json, :is_active, :created_by, :now)
                """,
                {
                    "id": skill_id,
                    "ws": workspace_id,
                    "name": name,
                    "skill_type": backend_skill_type or skill_type,
                    "query_id": query_id,
                    "config_json": config_str,
                    "is_active": is_active,
                    "created_by": user_id,
                    "now": datetime.now(timezone.utc),
                },
            )
            _sync_skill_schedule(
                sql,
                skill_id=skill_id,
                workspace_id=workspace_id,
                config_json=config_json,
                skill_is_active=is_active,
            )
            rows = sql.execute_query_mappings(
                """
                SELECT qs.id, qs.workspace_id, qs.name, qs.skill_type, qs.query_id, qs.config_json,
                       qs.is_active, qs.created_by, qs.created_at, qs.updated_at,
                       NULL AS last_run_at, 0 AS run_count
                FROM query_skills qs
                WHERE qs.id = :id
                """,
                {"id": skill_id},
            )
            return {"data": _normalize_skill_row(dict(rows[0])) if rows else {"id": skill_id}}, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skills create failed")
            return {"error": "skills create failed"}, 500


@skills_ns.route("/<string:skill_id>")
class SkillDetail(ForgeResource):
    @token_required
    @require_access("skills")
    @require_ownership("QuerySkill", "skill_id", "skills:admin", check_read=True)
    def get(self, skill_id: str):
        try:
            workspace_id = extract_workspace_id()
            from app.adapters.mysql_sql_executor import ForgeMetaSQL

            sql = ForgeMetaSQL()
            rows = sql.execute_query_mappings(
                """
                SELECT qs.id, qs.workspace_id, qs.name, qs.skill_type, qs.query_id, qs.config_json,
                       qs.is_active, qs.created_by, qs.created_at, qs.updated_at,
                       MAX(se.started_at) AS last_run_at,
                       COUNT(se.id) AS run_count
                FROM query_skills qs
                LEFT JOIN skill_executions se
                  ON se.skill_id = qs.id
                 AND se.workspace_id = qs.workspace_id
                WHERE qs.id = :id AND qs.workspace_id = :ws
                GROUP BY qs.id, qs.workspace_id, qs.name, qs.skill_type, qs.query_id, qs.config_json,
                         qs.is_active, qs.created_by, qs.created_at, qs.updated_at
                LIMIT 1
                """,
                {"id": skill_id, "ws": workspace_id},
            )
            if not rows:
                raise ForgeError(f"Skill {skill_id} not found", status_code=404)
            return {"data": _normalize_skill_row(dict(rows[0]))}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skills get failed skill_id=%s", skill_id)
            return {"error": "skills get failed"}, 500

    @token_required
    @require_access("skills", role="admin")
    @require_ownership("QuerySkill", "skill_id", "skills:admin", check_read=True)
    @skills_ns.expect(_skill_update_model, validate=False)
    def put(self, skill_id: str):
        try:
            workspace_id = extract_workspace_id()
            body: Dict[str, Any] = request.get_json(silent=True) or {}

            from app.adapters.mysql_sql_executor import ForgeMetaSQL
            import json as _json

            sql = ForgeMetaSQL()
            existing_rows = sql.execute_query_mappings(
                """
                SELECT id, skill_type, config_json, is_active
                FROM query_skills
                WHERE id = :id AND workspace_id = :ws
                LIMIT 1
                """,
                {"id": skill_id, "ws": workspace_id},
            )
            if not existing_rows:
                raise ForgeError(f"Skill {skill_id} not found", status_code=404)
            existing = dict(existing_rows[0])

            updates: Dict[str, Any] = {}
            if "name" in body and body["name"] is not None:
                updates["name"] = str(body["name"]).strip()
            if "skill_type" in body and body["skill_type"] is not None:
                updates["skill_type"] = _backend_skill_type(str(body["skill_type"]).strip())
            if "query_id" in body:
                updates["query_id"] = body["query_id"] or None
            if {
                "config_json", "config", "description", "status", "trigger", "conditions",
                "actions", "workflow", "query_name", "condition_mode", "check_mode",
                "alert_mode", "resolution_mode", "severity", "is_active",
            } & set(body):
                next_config, _, next_is_active = _config_from_request(
                    body,
                    existing_row=existing,
                )
                updates["config_json"] = _json.dumps(next_config) if next_config is not None else None
                if next_is_active is not None:
                    updates["is_active"] = next_is_active
            elif "is_active" in body and body["is_active"] is not None:
                updates["is_active"] = int(body["is_active"])

            if not updates:
                raise ForgeError("No updatable fields provided", status_code=400)

            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            updates["id"] = skill_id
            sql.execute_write(
                f"UPDATE query_skills SET {set_clause}, updated_at = :updated_at WHERE id = :id",
                {**updates, "updated_at": datetime.now(timezone.utc)},
            )
            next_config_json = updates.get("config_json", existing.get("config_json"))
            next_is_active_value = updates.get("is_active", existing.get("is_active"))
            _sync_skill_schedule(
                sql,
                skill_id=skill_id,
                workspace_id=workspace_id,
                config_json=next_config_json,
                skill_is_active=int(next_is_active_value or 0),
            )
            rows = sql.execute_query_mappings(
                """
                SELECT qs.id, qs.workspace_id, qs.name, qs.skill_type, qs.query_id, qs.config_json,
                       qs.is_active, qs.created_by, qs.created_at, qs.updated_at,
                       MAX(se.started_at) AS last_run_at,
                       COUNT(se.id) AS run_count
                FROM query_skills qs
                LEFT JOIN skill_executions se
                  ON se.skill_id = qs.id
                 AND se.workspace_id = qs.workspace_id
                WHERE qs.id = :id
                GROUP BY qs.id, qs.workspace_id, qs.name, qs.skill_type, qs.query_id, qs.config_json,
                         qs.is_active, qs.created_by, qs.created_at, qs.updated_at
                """,
                {"id": skill_id},
            )
            return {"data": _normalize_skill_row(dict(rows[0])) if rows else {"id": skill_id}}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skills update failed skill_id=%s", skill_id)
            return {"error": "skills update failed"}, 500

    @token_required
    @require_access("skills", role="admin")
    @require_ownership("QuerySkill", "skill_id", "skills:admin", check_read=True)
    @skills_ns.expect(_skill_update_model, validate=False)
    def patch(self, skill_id: str):
        return self.put(skill_id=skill_id)

    @token_required
    @require_access("skills", role="admin")
    @require_ownership("QuerySkill", "skill_id", "skills:admin", check_read=True)
    def delete(self, skill_id: str):
        try:
            workspace_id = extract_workspace_id()
            from app.adapters.mysql_sql_executor import ForgeMetaSQL

            sql = ForgeMetaSQL()
            existing = sql.execute_query_mappings(
                "SELECT id FROM query_skills WHERE id = :id AND workspace_id = :ws LIMIT 1",
                {"id": skill_id, "ws": workspace_id},
            )
            if not existing:
                raise ForgeError(f"Skill {skill_id} not found", status_code=404)
            sql.execute_write(
                "UPDATE query_skills SET is_active = 0, updated_at = :now WHERE id = :id",
                {"now": datetime.now(timezone.utc), "id": skill_id},
            )
            sql.execute_write(
                """
                UPDATE skill_schedules
                SET is_active = 0, next_run_at = NULL, updated_at = :now
                WHERE skill_id = :skill_id AND workspace_id = :ws
                """,
                {"now": datetime.now(timezone.utc), "skill_id": skill_id, "ws": workspace_id},
            )
            return {"message": "skill deactivated", "skill_id": skill_id}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skills delete failed skill_id=%s", skill_id)
            return {"error": "skills delete failed"}, 500


@skills_ns.route("/<string:skill_id>/execute")
class SkillExecute(ForgeResource):
    @token_required
    @require_access("skills")
    @require_ownership("QuerySkill", "skill_id", "skills:admin", check_read=True)
    @skills_ns.response(201, "Execution queued", _execute_response_model)
    def post(self, skill_id: str):
        try:
            workspace_id = extract_workspace_id()
            user_id = getattr(g, "user_id", None) or "unknown"

            from app.adapters.mysql_sql_executor import ForgeMetaSQL

            sql = ForgeMetaSQL()
            existing = sql.execute_query_mappings(
                "SELECT id FROM query_skills WHERE id = :id AND workspace_id = :ws AND is_active = 1 LIMIT 1",
                {"id": skill_id, "ws": workspace_id},
            )
            if not existing:
                raise ForgeError(f"Skill {skill_id} not found or inactive", status_code=404)

            execution_id = str(uuid.uuid4())
            job_id = str(uuid.uuid4())

            sql.execute_write(
                """
                INSERT INTO skill_executions (id, skill_id, workspace_id, job_id, status, triggered_by, created_at)
                VALUES (:id, :skill_id, :workspace_id, :job_id, 'queued', :triggered_by, CURRENT_TIMESTAMP)
                """,
                {
                    "id": execution_id,
                    "skill_id": skill_id,
                    "workspace_id": workspace_id,
                    "job_id": job_id,
                    "triggered_by": str(user_id),
                },
            )

            from app.tasks.skill_runner import execute_skill_task

            execute_skill_task.apply_async(
                kwargs={
                    "skill_id": skill_id,
                    "workspace_id": workspace_id,
                    "execution_id": execution_id,
                    "triggered_by": str(user_id),
                },
                task_id=job_id,
            )

            return {
                "execution_id": execution_id,
                "job_id": job_id,
                "status": "queued",
            }, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skills execute failed skill_id=%s", skill_id)
            return {"error": "skills execute failed"}, 500


@skills_ns.route("/<string:skill_id>/executions")
class SkillExecutionList(ForgeResource):
    @token_required
    @require_access("skills")
    @require_ownership("QuerySkill", "skill_id", "skills:admin", check_read=True)
    @skills_ns.doc(params={"page": "Page number (default 1)", "page_size": "Page size (default 20, max 100)"})
    def get(self, skill_id: str):
        try:
            workspace_id = extract_workspace_id()
            page = int_arg("page", 1)
            page_size = min(int_arg("page_size", 20), 100)
            offset = (page - 1) * page_size

            from app.adapters.mysql_sql_executor import ForgeMetaSQL

            sql = ForgeMetaSQL()
            rows = sql.execute_query_mappings(
                """
                SELECT id, skill_id, workspace_id, schedule_id, job_id, status,
                       triggered_by, started_at, completed_at AS finished_at,
                       CASE
                         WHEN started_at IS NOT NULL AND completed_at IS NOT NULL
                         THEN TIMESTAMPDIFF(MICROSECOND, started_at, completed_at) DIV 1000
                         ELSE NULL
                       END AS duration_ms,
                       COALESCE(error_message, CASE WHEN status = 'success' THEN 'Run complete.' ELSE 'Run queued.' END) AS message,
                       error_message, result_json, created_at
                FROM skill_executions
                WHERE skill_id = :skill_id AND workspace_id = :ws
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """,
                {"skill_id": skill_id, "ws": workspace_id, "limit": page_size, "offset": offset},
            )
            total_rows = sql.execute_query_mappings(
                "SELECT COUNT(*) AS cnt FROM skill_executions WHERE skill_id = :skill_id AND workspace_id = :ws",
                {"skill_id": skill_id, "ws": workspace_id},
            )
            total = int((total_rows[0]["cnt"] if total_rows else 0) or 0)
            return {
                "data": [_normalize_skill_run_row(dict(r)) for r in rows],
                "page": page,
                "page_size": page_size,
                "total": total,
            }, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skill executions list failed skill_id=%s", skill_id)
            return {"error": "skill executions list failed"}, 500


@skills_ns.route("/<string:skill_id>/runs")
class SkillRunListAlias(ForgeResource):
    @token_required
    @require_access("skills")
    @require_ownership("QuerySkill", "skill_id", "skills:admin", check_read=True)
    def get(self, skill_id: str):
        return SkillExecutionList().get(skill_id=skill_id)


@skills_ns.route("/schedules")
class SkillScheduleList(ForgeResource):
    @token_required
    @require_access("skills")
    @skills_ns.doc(params={"page": "Page number (default 1)", "page_size": "Page size (default 20, max 100)"})
    def get(self):
        try:
            workspace_id = extract_workspace_id()
            page = int_arg("page", 1)
            page_size = min(int_arg("page_size", 20), 100)
            offset = (page - 1) * page_size

            from app.adapters.mysql_sql_executor import ForgeMetaSQL

            sql = ForgeMetaSQL()
            rows = sql.execute_query_mappings(
                """
                SELECT id, skill_id, workspace_id, cron_expr, timezone,
                       next_run_at, last_run_at, is_active, catch_up, created_at, updated_at
                FROM skill_schedules
                WHERE workspace_id = :ws
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """,
                {"ws": workspace_id, "limit": page_size, "offset": offset},
            )
            total_rows = sql.execute_query_mappings(
                "SELECT COUNT(*) AS cnt FROM skill_schedules WHERE workspace_id = :ws",
                {"ws": workspace_id},
            )
            total = int((total_rows[0]["cnt"] if total_rows else 0) or 0)
            return {
                "data": [_serialize_schedule_row(dict(r)) for r in rows],
                "page": page,
                "page_size": page_size,
                "total": total,
            }, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skill schedules list failed")
            return {"error": "skill schedules list failed"}, 500


@skills_ns.route("/<string:skill_id>/schedules")
class SkillScheduleCreate(ForgeResource):
    @token_required
    @require_access("skills", role="admin")
    @require_ownership("QuerySkill", "skill_id", "skills:admin", check_read=True)
    @skills_ns.expect(_schedule_create_model, validate=False)
    def post(self, skill_id: str):
        try:
            workspace_id = extract_workspace_id()
            body: Dict[str, Any] = request.get_json(silent=True) or {}

            cron_expr = str(body.get("cron_expr") or "").strip()
            if not cron_expr:
                raise ForgeError("cron_expr is required", status_code=400)

            timezone_str = str(body.get("timezone") or "UTC").strip() or "UTC"
            is_active = int(body.get("is_active", 1))
            errors = validate_cron(cron_expr, timezone_str)
            if errors:
                raise ForgeError("; ".join(errors), status_code=400)
            next_run_at = None if not is_active else _resolve_next_run_at(
                cron_expr=cron_expr,
                timezone_name=timezone_str,
                next_run_at_raw=body.get("next_run_at"),
            )

            from app.adapters.mysql_sql_executor import ForgeMetaSQL

            sql = ForgeMetaSQL()
            existing = sql.execute_query_mappings(
                "SELECT id FROM query_skills WHERE id = :id AND workspace_id = :ws AND is_active = 1 LIMIT 1",
                {"id": skill_id, "ws": workspace_id},
            )
            if not existing:
                raise ForgeError(f"Skill {skill_id} not found or inactive", status_code=404)

            schedule_id = str(uuid.uuid4())
            sql.execute_write(
                """
                INSERT INTO skill_schedules (id, skill_id, workspace_id, cron_expr, timezone, next_run_at, is_active, created_at)
                VALUES (:id, :skill_id, :workspace_id, :cron_expr, :timezone, :next_run_at, :is_active, CURRENT_TIMESTAMP)
                """,
                {
                    "id": schedule_id,
                    "skill_id": skill_id,
                    "workspace_id": workspace_id,
                    "cron_expr": cron_expr,
                    "timezone": timezone_str,
                    "next_run_at": next_run_at,
                    "is_active": is_active,
                },
            )
            rows = sql.execute_query_mappings(
                "SELECT id, skill_id, workspace_id, cron_expr, timezone, next_run_at, last_run_at, is_active, catch_up, created_at, updated_at FROM skill_schedules WHERE id = :id",
                {"id": schedule_id},
            )
            return {"data": _serialize_schedule_row(dict(rows[0])) if rows else {"id": schedule_id}}, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skill schedule create failed skill_id=%s", skill_id)
            return {"error": "skill schedule create failed"}, 500


@skills_ns.route("/schedules/<string:schedule_id>")
class SkillScheduleDetail(ForgeResource):
    @token_required
    @require_access("skills", role="admin")
    @skills_ns.expect(_schedule_update_model, validate=False)
    def put(self, schedule_id: str):
        try:
            workspace_id = extract_workspace_id()
            body: Dict[str, Any] = request.get_json(silent=True) or {}

            from app.adapters.mysql_sql_executor import ForgeMetaSQL

            sql = ForgeMetaSQL()
            existing = sql.execute_query_mappings(
                """
                SELECT id, cron_expr, timezone, next_run_at, is_active
                FROM skill_schedules
                WHERE id = :id AND workspace_id = :ws
                LIMIT 1
                """,
                {"id": schedule_id, "ws": workspace_id},
            )
            if not existing:
                raise ForgeError(f"Schedule {schedule_id} not found", status_code=404)

            updates: Dict[str, Any] = {}
            if "cron_expr" in body and body["cron_expr"] is not None:
                updates["cron_expr"] = str(body["cron_expr"]).strip()
            if "timezone" in body and body["timezone"] is not None:
                updates["timezone"] = str(body["timezone"]).strip()
            if "next_run_at" in body:
                updates["next_run_at"] = body["next_run_at"] or None
            if "is_active" in body and body["is_active"] is not None:
                updates["is_active"] = int(body["is_active"])

            if not updates:
                raise ForgeError("No updatable fields provided", status_code=400)

            next_cron_expr = str(updates.get("cron_expr") or existing[0].get("cron_expr") or "").strip()
            next_timezone = str(updates.get("timezone") or existing[0].get("timezone") or "UTC").strip() or "UTC"
            next_is_active = int(updates.get("is_active", existing[0].get("is_active") or 0) or 0)
            errors = validate_cron(next_cron_expr, next_timezone)
            if errors:
                raise ForgeError("; ".join(errors), status_code=400)
            updates["next_run_at"] = None if not next_is_active else _resolve_next_run_at(
                cron_expr=next_cron_expr,
                timezone_name=next_timezone,
                next_run_at_raw=body.get("next_run_at") if "next_run_at" in body else None,
            )

            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            updates["id"] = schedule_id
            sql.execute_write(
                f"UPDATE skill_schedules SET {set_clause}, updated_at = :updated_at WHERE id = :id",
                {**updates, "updated_at": datetime.now(timezone.utc)},
            )
            rows = sql.execute_query_mappings(
                "SELECT id, skill_id, workspace_id, cron_expr, timezone, next_run_at, last_run_at, is_active, catch_up, created_at, updated_at FROM skill_schedules WHERE id = :id",
                {"id": schedule_id},
            )
            return {"data": _serialize_schedule_row(dict(rows[0])) if rows else {"id": schedule_id}}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skill schedule update failed schedule_id=%s", schedule_id)
            return {"error": "skill schedule update failed"}, 500


@skills_ns.route("/scheduler/status")
class SchedulerStatus(ForgeResource):
    @token_required
    @require_access("skills")
    def get(self):
        """
        Return Beat scheduler health. Used by ops dashboards and
        the SkillBuilder UI to warn when the scheduler is not running.
        """
        try:
            health = get_scheduler_health()
            status_code = 200 if health["healthy"] else 503
            return health, status_code
        except Exception:
            logger.exception("scheduler status check failed")
            return {"error": "scheduler status check failed"}, 500


@skills_ns.route("/<string:skill_id>/schedule/upcoming")
class SkillScheduleUpcoming(ForgeResource):
    @token_required
    @require_access("skills")
    def get(self, skill_id: str):
        """
        Return the next N scheduled run times for a skill.
        Used by the SkillBuilder UI to preview when a skill will next fire.

        Query params:
          n  — number of upcoming runs to return (default 5, max 20)
        """
        try:
            workspace_id = extract_workspace_id()
            from app.adapters.mysql_sql_executor import ForgeMetaSQL

            sql = ForgeMetaSQL()
            schedule_rows = sql.execute_query_mappings(
                """
                SELECT cron_expr, timezone FROM skill_schedules
                WHERE skill_id = :skill_id AND workspace_id = :ws AND is_active = 1
                ORDER BY created_at DESC LIMIT 1
                """,
                {"skill_id": skill_id, "ws": workspace_id},
            )
            if not schedule_rows:
                return {"upcoming": [], "reason": "No schedule configured."}, 200

            row = schedule_rows[0]
            cron_expr = str(row["cron_expr"] or "")
            timezone_str = str(row["timezone"] or "UTC")

            if not cron_expr:
                return {"upcoming": [], "reason": "No cron expression configured."}, 200

            n = min(int(request.args.get("n", 5) or 5), 20)
            runs = next_n_runs(expression=cron_expr, timezone_name=timezone_str, n=n)
            return {
                "upcoming": runs,
                "cron_expr": cron_expr,
                "timezone": timezone_str,
            }, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skill schedule upcoming failed skill_id=%s", skill_id)
            return {"error": "skill schedule upcoming failed"}, 500


@skills_ns.route("/<string:skill_id>/acknowledge")
class SkillAlertAcknowledge(ForgeResource):
    @token_required
    @require_access("skills")
    @require_ownership("QuerySkill", "skill_id", "skills:admin", check_read=True)
    def post(self, skill_id: str):
        """
        Manually acknowledge an alert. Sets alert_acknowledged_at to now.
        Only relevant for threshold_alert skills with resolution_mode="manual".
        """
        try:
            workspace_id = extract_workspace_id()
            from app.adapters.mysql_sql_executor import ForgeMetaSQL

            sql = ForgeMetaSQL()
            rows = sql.execute_query_mappings(
                "SELECT id, skill_type FROM query_skills WHERE id = :id AND workspace_id = :ws AND is_active = 1 LIMIT 1",
                {"id": skill_id, "ws": workspace_id},
            )
            if not rows:
                raise ForgeError(f"Skill {skill_id} not found", status_code=404)

            if str(rows[0]["skill_type"]) != "threshold_alert":
                return {"error": "Only threshold_alert skills support acknowledgement."}, 400

            now = datetime.now(timezone.utc)
            sql.execute_write(
                "UPDATE query_skills SET alert_acknowledged_at = :now WHERE id = :id",
                {"now": now, "id": skill_id},
            )
            return {"acknowledged": True, "acknowledged_at": now.isoformat()}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skill acknowledge failed skill_id=%s", skill_id)
            return {"error": "skill acknowledge failed"}, 500


@skills_ns.route("/schedule/validate")
class ScheduleValidate(ForgeResource):
    @token_required
    @require_access("skills")
    def post(self):
        """
        Validate a cron expression and return next 5 run times.
        Called by the SkillBuilder UI on every cron expression change.
        """
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            expression, timezone_name = _cron_expr_from_validate_request(body)

            errors = validate_cron(expression, timezone_name)
            if errors:
                return {"valid": False, "errors": errors, "upcoming": [], "cron_expression": expression}, 200

            upcoming = next_n_runs(expression, timezone_name, n=5)
            return {
                "valid": True,
                "errors": [],
                "upcoming": upcoming,
                "cron_expression": expression,
                "timezone": timezone_name,
            }, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("schedule validate failed")
            return {"error": "schedule validate failed"}, 500


__all__ = ["skills_ns"]
