from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

from app.exceptions.forge_error import ForgeError
from app.skills.schedule_utils import next_n_runs, validate_cron

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


def serialize_row(row: dict) -> dict:
    import json as _json

    out = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif k == "config_json" and isinstance(v, str):
            try:
                out[k] = _json.loads(v)
            except (TypeError, ValueError, _json.JSONDecodeError):
                out[k] = v
        else:
            out[k] = v
    return out


def json_object(value: Any) -> dict[str, Any]:
    import json as _json

    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = _json.loads(value)
        except (TypeError, ValueError, _json.JSONDecodeError):
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def to_list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def split_csv_or_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def destination_id_from_config(config: dict[str, Any]) -> int | None:
    raw = config.get("destination_id")
    if raw in (None, "", 0, "0"):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def frontend_skill_type(
    raw_skill_type: str,
    *,
    meta: dict[str, Any],
    actions: list[dict[str, Any]],
) -> str:
    explicit = str(meta.get("skill_type") or "").strip()
    if explicit:
        return explicit
    backend = str(raw_skill_type or "").strip()
    if backend == "webhook_delivery":
        for action in actions:
            if str(action.get("type") or "").strip() == "slack_delivery":
                return "slack_delivery"
    return _BACKEND_TO_FRONTEND_SKILL_TYPE.get(backend, backend)


def backend_skill_type(raw_skill_type: str) -> str:
    normalized = str(raw_skill_type or "").strip()
    return _FRONTEND_TO_BACKEND_SKILL_TYPE.get(normalized, normalized)


def status_from_row(*, meta: dict[str, Any], row: dict[str, Any]) -> str:
    explicit = str(meta.get("status") or "").strip().lower()
    if explicit in {"draft", "active", "paused", "error"}:
        return explicit
    return "active" if int(row.get("is_active") or 0) else "draft"


def default_trigger() -> dict[str, Any]:
    return {
        "id": "trigger_schedule",
        "kind": "trigger",
        "type": "schedule",
        "label": "Schedule",
        "enabled": True,
        "config": {"frequency": "daily", "time": "08:00", "timezone": "UTC"},
    }


def workflow_from_parts(
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


def extract_meta(config_json: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    config = json_object(config_json)
    meta = json_object(config.get(_SKILL_META_KEY))
    runtime_config = {k: v for k, v in config.items() if k != _SKILL_META_KEY}
    return runtime_config, meta


def derive_channels_from_actions(actions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    channels: list[dict[str, Any]] = []
    for action in actions:
        action_type = str(action.get("type") or "").strip()
        cfg = json_object(action.get("config"))
        destination_id = destination_id_from_config(cfg)
        if action_type == "email_report":
            if destination_id is not None:
                channels.append({"type": "email", "destination_id": destination_id})
                continue
            recipients = split_csv_or_list(cfg.get("recipients"))
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
            channel_type = (
                str(cfg.get("channel_type") or "slack").strip().lower() or "slack"
            )
            if channel_type not in {"slack", "teams", "webhook"}:
                channel_type = "slack"
            if destination_id is not None:
                channels.append({"type": channel_type, "destination_id": destination_id})
                continue
            webhook_url = str(
                cfg.get("webhook_url")
                or cfg.get("endpoint_url")
                or cfg.get("url")
                or ""
            ).strip()
            if webhook_url:
                channel_config: dict[str, Any] = {"type": channel_type}
                if channel_type == "webhook":
                    channel_config["url"] = webhook_url
                    channel_config["method"] = (
                        str(cfg.get("method") or "POST").strip().upper() or "POST"
                    )
                    headers = json_object(cfg.get("headers_json") or cfg.get("headers"))
                    if headers:
                        channel_config["headers"] = headers
                    auth_token = str(cfg.get("auth_token") or "").strip()
                    if auth_token:
                        channel_config["auth_token"] = auth_token
                else:
                    channel_config["webhook_url"] = webhook_url
                channels.append(channel_config)
    return channels


def runtime_config_from_meta(
    *,
    backend_skill_type: str,
    meta: dict[str, Any],
    existing_runtime: dict[str, Any],
) -> dict[str, Any]:
    actions = to_list_of_dicts(meta.get("actions"))
    conditions = to_list_of_dicts(meta.get("conditions"))
    trigger = json_object(meta.get("trigger"))
    description = str(meta.get("description") or "").strip()

    if backend_skill_type == "email_delivery":
        action = next(
            (a for a in actions if str(a.get("type") or "") == "email_report"),
            actions[0] if actions else {},
        )
        cfg = json_object(action.get("config"))
        destination_id = destination_id_from_config(cfg)
        return {
            **existing_runtime,
            "destination_id": destination_id,
            "recipients": split_csv_or_list(cfg.get("recipients")),
            "subject": str(cfg.get("subject") or "QueryForge report"),
            "reply_to": cfg.get("reply_to") or None,
            "include_summary": bool(cfg.get("include_ai_summary", True)),
        }

    if backend_skill_type == "ai_summary_digest":
        action = next(
            (a for a in actions if str(a.get("type") or "") == "ai_summary_digest"),
            actions[0] if actions else {},
        )
        cfg = json_object(action.get("config"))
        destination_id = destination_id_from_config(cfg)
        return {
            **existing_runtime,
            "destination_id": destination_id,
            "recipients": split_csv_or_list(cfg.get("recipients")),
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
                a
                for a in actions
                if str(a.get("type") or "") in {"webhook_delivery", "slack_delivery"}
            ),
            actions[0] if actions else {},
        )
        cfg = json_object(action.get("config"))
        channel_type = str(
            cfg.get("channel_type")
            or ("slack" if str(action.get("type") or "") == "slack_delivery" else "slack")
        ).strip().lower()
        if channel_type not in {"slack", "teams", "webhook"}:
            channel_type = "slack"
        destination_id = destination_id_from_config(cfg)
        return {
            **existing_runtime,
            "channel_type": channel_type,
            "channels": derive_channels_from_actions(actions),
            "destination_id": destination_id,
            "webhook_url": str(
                cfg.get("webhook_url")
                or cfg.get("endpoint_url")
                or cfg.get("url")
                or ""
            ).strip(),
            "url": str(
                cfg.get("url")
                or cfg.get("endpoint_url")
                or cfg.get("webhook_url")
                or ""
            ).strip(),
            "method": str(cfg.get("method") or "POST").strip().upper() or "POST",
            "headers": json_object(cfg.get("headers_json") or cfg.get("headers")),
            "auth_token": str(cfg.get("auth_token") or "").strip() or None,
            "message": str(
                cfg.get("message_template") or cfg.get("message") or description
            ).strip(),
            "format": "table" if bool(cfg.get("include_table_preview")) else "summary",
            "max_rows": int(cfg.get("max_rows") or 10),
            "send_if_empty": bool(cfg.get("send_if_empty", False)),
            "severity": str(cfg.get("severity") or "info"),
        }

    if backend_skill_type == "threshold_alert":
        runtime_conditions: list[dict[str, Any]] = []
        for condition in conditions:
            cond_type = str(condition.get("type") or "").strip()
            cfg = json_object(condition.get("config"))
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
                    runtime_conditions.append(
                        {"type": "ai_expectation", "prompt": expression}
                    )
        if not runtime_conditions and trigger and str(trigger.get("type") or "") == "threshold_alert":
            trigger_cfg = json_object(trigger.get("config"))
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
            "channels": derive_channels_from_actions(actions),
            "severity": str(meta.get("severity") or "warning"),
            "message": description,
        }

    if backend_skill_type == "data_freshness_check":
        runtime_checks: list[dict[str, Any]] = []
        if trigger and str(trigger.get("type") or "") == "data_freshness_check":
            trigger_cfg = json_object(trigger.get("config"))
            runtime_checks.append(
                {
                    "type": "timestamp_stale"
                    if str(trigger_cfg.get("freshness_column") or "").strip()
                    else "no_new_rows",
                    "column": str(trigger_cfg.get("freshness_column") or "").strip()
                    or None,
                    "window_mode": "fixed",
                    "fixed_hours": max(int(trigger_cfg.get("interval_value") or 1) * 24, 1),
                }
            )
        for condition in conditions:
            if str(condition.get("type") or "").strip() == "no_new_rows":
                cfg = json_object(condition.get("config"))
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
            "channels": derive_channels_from_actions(actions),
            "severity": str(meta.get("severity") or "warning"),
            "message": description,
        }

    return existing_runtime


def config_from_request(
    body: dict[str, Any],
    *,
    existing_row: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None, int | None]:
    existing_runtime: dict[str, Any] = {}
    existing_meta: dict[str, Any] = {}
    existing_is_active = None
    if existing_row:
        existing_runtime, existing_meta = extract_meta(existing_row.get("config_json"))
        existing_is_active = int(existing_row.get("is_active") or 0)

    explicit_config = None
    if "config_json" in body or "config" in body:
        explicit_config = json_object(body.get("config_json") or body.get("config"))

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
    resolved_backend_type = backend_skill_type(input_skill_type) if input_skill_type else None
    if input_skill_type:
        meta["skill_type"] = input_skill_type

    for key in ("trigger", "workflow"):
        if key in body:
            meta[key] = body.get(key)
    for key in ("conditions", "actions"):
        if key in body:
            meta[key] = body.get(key) or []

    if "trigger" in meta or "conditions" in meta or "actions" in meta:
        trigger = json_object(meta.get("trigger")) or default_trigger()
        conditions = to_list_of_dicts(meta.get("conditions"))
        actions = to_list_of_dicts(meta.get("actions"))
        meta["trigger"] = trigger
        meta["conditions"] = conditions
        meta["actions"] = actions
        meta["workflow"] = workflow_from_parts(trigger, conditions, actions)

    if "status" in body:
        meta["status"] = body.get("status")
    status = str(meta.get("status") or "").strip().lower() or None
    is_active = existing_is_active
    if status:
        is_active = 1 if status == "active" else 0
    elif "is_active" in body and body.get("is_active") is not None:
        is_active = int(body.get("is_active"))

    if explicit_config is None and not meta and existing_row is None:
        return None, resolved_backend_type, is_active

    runtime = explicit_config if explicit_config is not None else dict(existing_runtime)
    if resolved_backend_type:
        runtime = runtime_config_from_meta(
            backend_skill_type=resolved_backend_type,
            meta=meta,
            existing_runtime=runtime,
        )

    config_payload = dict(runtime)
    if meta:
        config_payload[_SKILL_META_KEY] = meta
    return config_payload or None, resolved_backend_type, is_active


def normalize_skill_row(row: dict[str, Any]) -> dict[str, Any]:
    runtime_config, meta = extract_meta(row.get("config_json"))
    trigger = json_object(meta.get("trigger")) or default_trigger()
    conditions = to_list_of_dicts(meta.get("conditions"))
    actions = to_list_of_dicts(meta.get("actions"))
    workflow = to_list_of_dicts(meta.get("workflow")) or workflow_from_parts(
        trigger,
        conditions,
        actions,
    )
    normalized_frontend_type = frontend_skill_type(
        str(row.get("skill_type") or ""),
        meta=meta,
        actions=actions,
    )

    out = serialize_row(dict(row))
    out["config_json"] = runtime_config
    out["description"] = meta.get("description")
    out["query_name"] = meta.get("query_name")
    out["status"] = status_from_row(meta=meta, row=row)
    out["skill_type"] = normalized_frontend_type
    out["trigger"] = trigger
    out["conditions"] = conditions
    out["actions"] = actions
    out["workflow"] = workflow
    return out


def normalize_skill_run_row(row: dict[str, Any]) -> dict[str, Any]:
    out = serialize_row(dict(row))
    result = json_object(out.get("result_json"))
    data = json_object(result.get("data"))
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


def time_parts(value: Any) -> tuple[int, int]:
    raw = str(value or "08:00").strip() or "08:00"
    try:
        hour_str, minute_str = raw.split(":", 1)
        hour = max(0, min(int(hour_str), 23))
        minute = max(0, min(int(minute_str), 59))
        return hour, minute
    except (TypeError, ValueError):
        return 8, 0


def cron_expr_from_trigger(trigger: dict[str, Any]) -> str:
    cfg = json_object(trigger.get("config"))
    frequency = str(cfg.get("frequency") or "daily").strip().lower()
    hour, minute = time_parts(cfg.get("time"))
    if frequency == "hourly":
        return f"{minute} * * * *"
    if frequency == "weekly":
        day = _DAY_OF_WEEK_TO_CRON.get(
            str(cfg.get("day_of_week") or "monday").strip().lower(),
            "1",
        )
        return f"{minute} {hour} * * {day}"
    if frequency == "monthly":
        return f"{minute} {hour} 1 * *"
    return f"{minute} {hour} * * *"


def cron_expr_from_validate_request(body: dict[str, Any]) -> tuple[str, str]:
    timezone_name = str(body.get("timezone") or "UTC").strip() or "UTC"
    expression = str(body.get("cron_expression") or "").strip()
    if expression:
        return expression, timezone_name

    trigger = json_object(body.get("trigger"))
    if trigger:
        cfg = json_object(trigger.get("config"))
        if not body.get("timezone") and cfg.get("timezone"):
            timezone_name = str(cfg.get("timezone") or "UTC").strip() or "UTC"
        return cron_expr_from_trigger(trigger), timezone_name

    raise ForgeError("cron_expression or trigger is required", status_code=400)


def normalize_next_run_at(value: Any) -> datetime | None:
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


def resolve_next_run_at(
    *,
    cron_expr: str,
    timezone_name: str,
    next_run_at_raw: Any = None,
) -> datetime | None:
    explicit = normalize_next_run_at(next_run_at_raw)
    if explicit is not None:
        return explicit
    upcoming = next_n_runs(cron_expr, timezone_name, n=1)
    if not upcoming:
        return None
    return normalize_next_run_at(upcoming[0])


def schedule_payload_from_meta(
    *,
    meta: dict[str, Any],
    skill_is_active: int,
) -> dict[str, Any] | None:
    trigger = json_object(meta.get("trigger"))
    if str(trigger.get("type") or "").strip() != "schedule":
        return None
    cfg = json_object(trigger.get("config"))
    is_trigger_active = bool(trigger.get("enabled", True)) and bool(
        cfg.get("active", True)
    )
    timezone_name = str(cfg.get("timezone") or "UTC").strip() or "UTC"
    cron_expr = cron_expr_from_trigger(trigger)
    errors = validate_cron(cron_expr, timezone_name)
    if errors:
        raise ForgeError("; ".join(errors), status_code=400)
    is_active = 1 if (skill_is_active and is_trigger_active) else 0
    return {
        "cron_expr": cron_expr,
        "timezone": timezone_name,
        "next_run_at": resolve_next_run_at(
            cron_expr=cron_expr,
            timezone_name=timezone_name,
        )
        if is_active
        else None,
        "is_active": is_active,
        "trigger": trigger,
    }


def latest_skill_schedule(sql: Any, *, skill_id: str, workspace_id: str) -> dict[str, Any] | None:
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


def serialize_schedule_row(row: dict[str, Any]) -> dict[str, Any]:
    out = serialize_row(dict(row))
    out["upcoming"] = (
        next_n_runs(
            str(row.get("cron_expr") or ""),
            str(row.get("timezone") or "UTC"),
            n=5,
        )
        if str(row.get("is_active") or 0) == "1" or int(row.get("is_active") or 0) == 1
        else []
    )
    return out


def sync_skill_schedule(
    sql: Any,
    *,
    skill_id: str,
    workspace_id: str,
    config_json: Any,
    skill_is_active: int,
) -> dict[str, Any] | None:
    _, meta = extract_meta(config_json)
    schedule_payload = (
        schedule_payload_from_meta(meta=meta, skill_is_active=skill_is_active)
        if meta
        else None
    )
    existing = latest_skill_schedule(sql, skill_id=skill_id, workspace_id=workspace_id)

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
    return latest_skill_schedule(sql, skill_id=skill_id, workspace_id=workspace_id)
