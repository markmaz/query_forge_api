"""
app/skills/data_freshness_check.py

Data Freshness Check skill — monitors query results for staleness and
alerts via email, Slack, and/or Microsoft Teams.

Staleness conditions (any combination, evaluated independently):
  no_new_rows       — row count hasn't increased since last run
  row_count_unchanged — row count is identical to last run (stricter)
  timestamp_stale   — a user-specified column's max value hasn't advanced
  no_rows           — query returns zero rows

Window modes:
  relative  — compare to last run snapshot (default)
  fixed     — alert if no change within N hours regardless of last run

Alert persistence modes:
  on_change   — alert once on transition to stale, resolve when fresh again
  every_run   — alert every run while stale

Delivery: email, Slack, Microsoft Teams (any combination)
Snapshot: stored in QuerySkill.last_alert_state (no new tables)
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.skills.base import BaseSkill, SkillContext, SkillResult
from app.skills.delivery import DeliveryPayload, get_channel
from app.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


@SkillRegistry.register
class DataFreshnessCheckSkill(BaseSkill):
    skill_type = "data_freshness_check"
    display_name = "Data Freshness Check"
    description = "Alert when query results stop changing — detect stale or missing data."
    supports_schedule = True
    supports_manual = True

    config_schema = {
        "type": "object",
        "required": ["checks", "channels"],
        "properties": {
            "checks": {
                "type": "array",
                "title": "Freshness checks",
                "description": "One or more staleness conditions to evaluate.",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["type"],
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": [
                                "no_new_rows",
                                "row_count_unchanged",
                                "timestamp_stale",
                                "no_rows",
                            ],
                            "title": "Check type",
                        },
                        "column": {
                            "type": "string",
                            "title": "Timestamp column",
                            "description": "Column containing timestamps to monitor.",
                            "ui:condition": {
                                "property": "type",
                                "enum": ["timestamp_stale"],
                            },
                        },
                        "window_mode": {
                            "type": "string",
                            "enum": ["relative", "fixed"],
                            "enumNames": [
                                "Relative — compare to last run",
                                "Fixed — alert if no change within N hours",
                            ],
                            "default": "relative",
                            "title": "Window mode",
                            "ui:condition": {
                                "property": "type",
                                "enum": [
                                    "no_new_rows",
                                    "row_count_unchanged",
                                    "timestamp_stale",
                                ],
                            },
                        },
                        "fixed_hours": {
                            "type": "integer",
                            "title": "Fixed window (hours)",
                            "description": "Alert if no new data in this many hours.",
                            "minimum": 1,
                            "default": 24,
                            "ui:condition": {
                                "property": "window_mode",
                                "enum": ["fixed"],
                            },
                        },
                    },
                },
                "ui:widget": "freshness-check-builder",
            },
            "check_mode": {
                "type": "string",
                "title": "Check logic",
                "enum": ["any", "all"],
                "enumNames": [
                    "Alert if ANY check detects staleness",
                    "Alert if ALL checks detect staleness",
                ],
                "default": "any",
                "ui:widget": "select",
            },
            "alert_mode": {
                "type": "string",
                "title": "Alert frequency",
                "enum": ["on_change", "every_run"],
                "enumNames": [
                    "Alert once — resolve when data is fresh again",
                    "Alert every run while data is stale",
                ],
                "default": "on_change",
                "ui:widget": "select",
            },
            "channels": {
                "type": "array",
                "title": "Delivery channels",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["type"],
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["email", "slack", "teams"],
                            "title": "Channel type",
                        },
                        "recipients": {
                            "type": "array",
                            "items": {"type": "string", "format": "email"},
                            "title": "Recipients",
                            "ui:condition": {"property": "type", "enum": ["email"]},
                        },
                        "webhook_url": {
                            "type": "string",
                            "title": "Webhook URL",
                            "ui:condition": {
                                "property": "type",
                                "enum": ["slack", "teams"],
                            },
                        },
                    },
                },
                "ui:widget": "channel-builder",
            },
            "severity": {
                "type": "string",
                "title": "Severity",
                "enum": ["info", "warning", "critical"],
                "default": "warning",
                "ui:widget": "select",
            },
            "message": {
                "type": "string",
                "title": "Custom alert message",
                "ui:widget": "textarea",
            },
        },
        "additionalProperties": False,
    }

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []

        checks = config.get("checks", [])
        if not checks:
            errors.append("At least one freshness check is required.")

        for i, check in enumerate(checks):
            ctype = check.get("type")
            if ctype not in ("no_new_rows", "row_count_unchanged", "timestamp_stale", "no_rows"):
                errors.append(f"Check {i+1}: unknown type {ctype!r}.")
                continue
            if ctype == "timestamp_stale" and not check.get("column", "").strip():
                errors.append(f"Check {i+1}: timestamp_stale requires a column name.")
            if check.get("window_mode") == "fixed":
                hours = check.get("fixed_hours")
                if not isinstance(hours, int) or hours < 1:
                    errors.append(f"Check {i+1}: fixed_hours must be a positive integer.")

        channels = config.get("channels", [])
        if not channels:
            errors.append("At least one delivery channel is required.")
        for i, ch in enumerate(channels):
            ctype = ch.get("type")
            if ctype == "email" and not ch.get("recipients"):
                errors.append(f"Channel {i+1}: email requires at least one recipient.")
            elif ctype in ("slack", "teams") and not ch.get("webhook_url", "").strip():
                errors.append(f"Channel {i+1}: {ctype} requires a webhook URL.")
            elif ctype not in ("email", "slack", "teams"):
                errors.append(f"Channel {i+1}: unknown channel type {ctype!r}.")

        return errors

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(self, context: SkillContext) -> SkillResult:
        cfg = context.config
        last_snapshot = self._load_snapshot(context)
        now = datetime.now(timezone.utc)

        # Evaluate all freshness checks
        stale_checks = []
        fresh_checks = []

        for check in cfg.get("checks", []):
            result = self._evaluate_check(check, context, last_snapshot, now)
            if result["stale"]:
                stale_checks.append(result)
            else:
                fresh_checks.append(result)

        # Apply check_mode logic
        check_mode = cfg.get("check_mode", "any")
        is_stale = (
            len(stale_checks) > 0
            if check_mode == "any"
            else len(stale_checks) == len(cfg.get("checks", []))
        )

        # Build and save new snapshot before deciding to alert
        new_snapshot = self._build_snapshot(context, stale_checks, fresh_checks, now)
        self._save_snapshot(context, new_snapshot)

        # Determine whether to alert
        should_alert = self._should_alert(cfg, is_stale, last_snapshot)

        if not should_alert:
            return SkillResult(
                success=True,
                message="Freshness checks passed — no alert triggered." if not is_stale
                        else "Data is stale but alert suppressed (on_change mode, already alerted).",
                data={
                    "is_stale": is_stale,
                    "stale_checks": len(stale_checks),
                    "alerted": False,
                },
            )

        # Deliver alert
        payload = self._build_payload(context, cfg, stale_checks, now)
        delivery_results = self._deliver(payload, cfg["channels"])
        any_delivered = any(r["success"] for r in delivery_results)

        return SkillResult(
            success=any_delivered,
            message=(
                f"Freshness alert sent via "
                f"{sum(r['success'] for r in delivery_results)}/{len(delivery_results)} channel(s)."
            ),
            data={
                "is_stale": is_stale,
                "stale_checks": len(stale_checks),
                "alerted": True,
                "delivery_results": delivery_results,
            },
        )

    # ------------------------------------------------------------------
    # Freshness check evaluators
    # ------------------------------------------------------------------

    def _evaluate_check(
        self,
        check: dict,
        context: SkillContext,
        last_snapshot: dict | None,
        now: datetime,
    ) -> dict:
        ctype = check["type"]

        if ctype == "no_rows":
            return self._check_no_rows(context)
        elif ctype == "no_new_rows":
            return self._check_no_new_rows(check, context, last_snapshot, now)
        elif ctype == "row_count_unchanged":
            return self._check_row_count_unchanged(check, context, last_snapshot, now)
        elif ctype == "timestamp_stale":
            return self._check_timestamp_stale(check, context, last_snapshot, now)

        return {"type": ctype, "stale": False, "message": f"Unknown check type: {ctype}"}

    def _check_no_rows(self, context: SkillContext) -> dict:
        stale = context.metadata.row_count == 0
        return {
            "type": "no_rows",
            "stale": stale,
            "message": "Query returned no rows." if stale else f"Query returned {context.metadata.row_count} rows.",
            "current_value": context.metadata.row_count,
        }

    def _check_no_new_rows(
        self,
        check: dict,
        context: SkillContext,
        last_snapshot: dict | None,
        now: datetime,
    ) -> dict:
        current_count = context.metadata.row_count
        window_mode = check.get("window_mode", "relative")

        if window_mode == "fixed":
            hours = check.get("fixed_hours", 24)
            last_change_at = self._parse_dt(
                (last_snapshot or {}).get("last_row_count_change_at")
            )
            if last_change_at is None:
                # No history — treat as fresh, record baseline
                return {
                    "type": "no_new_rows",
                    "stale": False,
                    "message": "No baseline recorded — establishing now.",
                    "current_value": current_count,
                }
            hours_since_change = (now - last_change_at).total_seconds() / 3600
            stale = hours_since_change >= hours
            return {
                "type": "no_new_rows",
                "stale": stale,
                "message": (
                    f"No new rows in {hours_since_change:.1f}h (threshold: {hours}h)."
                    if stale else
                    f"Rows last changed {hours_since_change:.1f}h ago (threshold: {hours}h)."
                ),
                "current_value": current_count,
                "hours_since_change": round(hours_since_change, 1),
            }

        # Relative mode — compare to last snapshot count
        if last_snapshot is None:
            return {
                "type": "no_new_rows",
                "stale": False,
                "message": "No baseline recorded — establishing now.",
                "current_value": current_count,
            }
        prev_count = last_snapshot.get("row_count", 0)
        stale = current_count <= prev_count
        return {
            "type": "no_new_rows",
            "stale": stale,
            "message": (
                f"Row count has not increased: {prev_count} → {current_count}."
                if stale else
                f"New rows detected: {prev_count} → {current_count}."
            ),
            "current_value": current_count,
            "previous_value": prev_count,
        }

    def _check_row_count_unchanged(
        self,
        check: dict,
        context: SkillContext,
        last_snapshot: dict | None,
        now: datetime,
    ) -> dict:
        current_count = context.metadata.row_count
        window_mode = check.get("window_mode", "relative")

        if window_mode == "fixed":
            hours = check.get("fixed_hours", 24)
            last_change_at = self._parse_dt(
                (last_snapshot or {}).get("last_row_count_change_at")
            )
            if last_change_at is None:
                return {
                    "type": "row_count_unchanged",
                    "stale": False,
                    "message": "No baseline recorded — establishing now.",
                    "current_value": current_count,
                }
            hours_since = (now - last_change_at).total_seconds() / 3600
            stale = hours_since >= hours
            return {
                "type": "row_count_unchanged",
                "stale": stale,
                "message": (
                    f"Row count unchanged for {hours_since:.1f}h (threshold: {hours}h)."
                    if stale else
                    f"Row count last changed {hours_since:.1f}h ago."
                ),
                "current_value": current_count,
            }

        if last_snapshot is None:
            return {
                "type": "row_count_unchanged",
                "stale": False,
                "message": "No baseline recorded — establishing now.",
                "current_value": current_count,
            }
        prev_count = last_snapshot.get("row_count", -1)
        stale = current_count == prev_count
        return {
            "type": "row_count_unchanged",
            "stale": stale,
            "message": (
                f"Row count unchanged at {current_count}."
                if stale else
                f"Row count changed: {prev_count} → {current_count}."
            ),
            "current_value": current_count,
            "previous_value": prev_count,
        }

    def _check_timestamp_stale(
        self,
        check: dict,
        context: SkillContext,
        last_snapshot: dict | None,
        now: datetime,
    ) -> dict:
        column = check["column"]
        window_mode = check.get("window_mode", "relative")

        # Extract max timestamp value from current results
        current_max_ts = self._extract_max_timestamp(context.results, column)
        if current_max_ts is None:
            return {
                "type": "timestamp_stale",
                "stale": True,
                "message": f"Column '{column}' not found or contains no parseable timestamps.",
                "column": column,
            }

        if window_mode == "fixed":
            hours = check.get("fixed_hours", 24)
            age_hours = (now - current_max_ts).total_seconds() / 3600
            stale = age_hours >= hours
            return {
                "type": "timestamp_stale",
                "stale": stale,
                "message": (
                    f"'{column}' last updated {age_hours:.1f}h ago (threshold: {hours}h)."
                    if stale else
                    f"'{column}' updated {age_hours:.1f}h ago — within {hours}h window."
                ),
                "column": column,
                "current_max_ts": current_max_ts.isoformat(),
                "age_hours": round(age_hours, 1),
            }

        # Relative mode — compare to snapshot
        if last_snapshot is None:
            return {
                "type": "timestamp_stale",
                "stale": False,
                "message": f"No baseline for '{column}' — establishing now.",
                "column": column,
                "current_max_ts": current_max_ts.isoformat(),
            }

        prev_ts_str = (last_snapshot.get("timestamp_values") or {}).get(column)
        prev_ts = self._parse_dt(prev_ts_str)
        if prev_ts is None:
            return {
                "type": "timestamp_stale",
                "stale": False,
                "message": f"No previous timestamp for '{column}' — establishing now.",
                "column": column,
                "current_max_ts": current_max_ts.isoformat(),
            }

        stale = current_max_ts <= prev_ts
        return {
            "type": "timestamp_stale",
            "stale": stale,
            "message": (
                f"'{column}' has not advanced: max is still {current_max_ts.strftime('%Y-%m-%d %H:%M')}."
                if stale else
                f"'{column}' advanced: {prev_ts.strftime('%Y-%m-%d %H:%M')} → {current_max_ts.strftime('%Y-%m-%d %H:%M')}."
            ),
            "column": column,
            "current_max_ts": current_max_ts.isoformat(),
            "previous_max_ts": prev_ts.isoformat(),
        }

    # ------------------------------------------------------------------
    # Alert mode logic
    # ------------------------------------------------------------------

    def _should_alert(
        self,
        cfg: dict,
        is_stale: bool,
        last_snapshot: dict | None,
    ) -> bool:
        if not is_stale:
            return False

        alert_mode = cfg.get("alert_mode", "on_change")
        if alert_mode == "every_run":
            return True

        # on_change — only alert on transition from fresh → stale
        was_stale = (last_snapshot or {}).get("is_stale", False)
        return not was_stale  # alert only when transitioning to stale

    # ------------------------------------------------------------------
    # Snapshot management
    # ------------------------------------------------------------------

    def _build_snapshot(
        self,
        context: SkillContext,
        stale_checks: list[dict],
        fresh_checks: list[dict],
        now: datetime,
    ) -> dict:
        snapshot: dict[str, Any] = {
            "is_stale": len(stale_checks) > 0,
            "row_count": context.metadata.row_count,
            "checked_at": now.isoformat(),
            "timestamp_values": {},
        }

        # Track when row count last changed (for fixed window checks)
        last_snapshot = self._load_snapshot(context)
        prev_count = (last_snapshot or {}).get("row_count")
        if prev_count != context.metadata.row_count:
            snapshot["last_row_count_change_at"] = now.isoformat()
        else:
            snapshot["last_row_count_change_at"] = (
                (last_snapshot or {}).get("last_row_count_change_at") or now.isoformat()
            )

        # Record max timestamp values for each timestamp_stale check
        for check in (stale_checks + fresh_checks):
            if check["type"] == "timestamp_stale" and check.get("current_max_ts"):
                col = check.get("column", "")
                snapshot["timestamp_values"][col] = check["current_max_ts"]

        return snapshot

    def _load_snapshot(self, context: SkillContext) -> dict | None:
        try:
            from app.models.query.skills import QuerySkill
            skill = QuerySkill.query.filter_by(
                query_id=context.query_id,
                workspace_id=context.workspace_id,
                skill_type=self.skill_type,
            ).first()
            return skill.last_alert_state if skill and skill.last_alert_state else None
        except Exception as exc:
            logger.warning("Could not load freshness snapshot: %s", exc)
            return None

    def _save_snapshot(self, context: SkillContext, snapshot: dict) -> None:
        try:
            from app.extensions import db
            from app.models.query.skills import QuerySkill
            skill = QuerySkill.query.filter_by(
                query_id=context.query_id,
                workspace_id=context.workspace_id,
                skill_type=self.skill_type,
            ).first()
            if skill:
                skill.last_alert_state = snapshot
                db.session.add(skill)
                db.session.commit()
        except Exception as exc:
            logger.warning("Could not save freshness snapshot: %s", exc)

    # ------------------------------------------------------------------
    # Delivery
    # ------------------------------------------------------------------

    def _deliver(
        self, payload: DeliveryPayload, channel_configs: list[dict]
    ) -> list[dict]:
        results = []
        for ch_config in channel_configs:
            ch_type = ch_config.get("type")
            try:
                channel = get_channel(ch_type)
                success, message = channel.send(payload, ch_config)
                results.append({"channel": ch_type, "success": success, "message": message})
            except Exception as exc:
                results.append({"channel": ch_type, "success": False, "message": str(exc)})
        return results

    def _build_payload(
        self,
        context: SkillContext,
        cfg: dict,
        stale_checks: list[dict],
        now: datetime,
    ) -> DeliveryPayload:
        custom_message = cfg.get("message", "")
        check_lines = [c["message"] for c in stale_checks]
        summary = (
            custom_message
            or f"Data freshness alert: {len(stale_checks)} check(s) failed on '{context.metadata.query_name}'"
        )
        detail_text = "\n".join([summary, ""] + [f"• {line}" for line in check_lines])
        detail_html = self._build_alert_html(context, cfg, stale_checks, custom_message, now)

        return DeliveryPayload(
            subject=f"{context.metadata.query_name} — Data Freshness Alert",
            summary=summary,
            detail_html=detail_html,
            detail_text=detail_text,
            query_name=context.metadata.query_name,
            workspace_id=context.workspace_id,
            query_id=context.query_id,
            conditions_failed=[{"type": c["type"], "message": c["message"]} for c in stale_checks],
            severity=cfg.get("severity", "warning"),
        )

    def _build_alert_html(
        self,
        context: SkillContext,
        cfg: dict,
        stale_checks: list[dict],
        custom_message: str,
        now: datetime,
    ) -> str:
        severity = cfg.get("severity", "warning")
        color = {"info": "#0078d4", "warning": "#f7630c", "critical": "#d13438"}.get(severity, "#f7630c")
        rows_html = "".join(
            f"<tr>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #eee;font-size:12px'>{c['type'].replace('_', ' ').title()}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #eee;font-size:12px'>{c['message']}</td>"
            f"</tr>"
            for c in stale_checks
        )
        custom_html = f"<p style='font-size:13px'>{custom_message}</p>" if custom_message else ""
        return f"""
<div style="font-family:sans-serif;max-width:640px;margin:0 auto">
  <div style="border-left:4px solid {color};padding:12px 16px;background:#fafafa;margin-bottom:16px">
    <strong style="color:{color}">{severity.upper()}</strong>
    &nbsp;Data Freshness Alert · {context.metadata.query_name}
  </div>
  {custom_html}
  <table style="width:100%;border-collapse:collapse">
    <thead>
      <tr style="background:#f0f0f0">
        <th style="padding:6px 8px;text-align:left;font-size:12px">Check</th>
        <th style="padding:6px 8px;text-align:left;font-size:12px">Detail</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
  <p style="color:#999;font-size:11px;margin-top:16px">
    QueryForge · {now.strftime('%Y-%m-%d %H:%M UTC')}
  </p>
</div>"""

    # ------------------------------------------------------------------
    # Timestamp utilities
    # ------------------------------------------------------------------

    def _extract_max_timestamp(
        self, rows: list[dict], column: str
    ) -> datetime | None:
        """Extract the maximum parseable datetime from a column across all rows."""
        max_dt: datetime | None = None
        for row in rows:
            val = row.get(column)
            if val is None:
                continue
            dt = self._parse_dt(str(val))
            if dt is not None:
                if max_dt is None or dt > max_dt:
                    max_dt = dt
        return max_dt

    def _parse_dt(self, value: str | None) -> datetime | None:
        """Parse a datetime string into a timezone-aware datetime. Returns None on failure."""
        if not value:
            return None
        formats = [
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%dT%H:%M:%S.%f%z",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(str(value)[:26], fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        return None
