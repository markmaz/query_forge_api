"""
app/skills/threshold_alert.py

Threshold Alert skill — evaluates conditions against query results and
delivers alerts via email, Slack, and/or Microsoft Teams.

Condition types:
  row_count         — alert when row count crosses a numeric threshold
  no_rows           — alert when query returns zero rows
  column_change_pct — alert when a column value changes by more than N% vs last run
  ai_expectation    — alert when LLM evaluates a natural language expectation as failed

Alert modes:
  every_run  — alert every time the skill runs and a condition fails
  on_change  — alert only when condition state changes (fail→pass or pass→fail)

Resolution modes (for on_change):
  auto       — resolved when all conditions pass on next run
  manual     — resolved when user acknowledges via API
  both       — configurable per skill; defaults to auto

Delivery channels: email, slack, teams (any combination)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import SQLAlchemyError

from app.exceptions.forge_error import ForgeError
from app.skills.base import BaseSkill, SkillContext
from app.skills.delivery import DeliveryPayload, get_channel
from app.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

AI_EXPECTATION_FALLBACK_ERRORS = (ForgeError, OSError, RuntimeError, TypeError, ValueError)
ALERT_STATE_FALLBACK_ERRORS = (OSError, RuntimeError, TypeError, ValueError, SQLAlchemyError)
DELIVERY_FALLBACK_ERRORS = (ForgeError, OSError, RuntimeError, TypeError, ValueError)


@SkillRegistry.register
class ThresholdAlertSkill(BaseSkill):
    skill_type = "threshold_alert"
    display_name = "Threshold Alert"
    description = "Alert via email, Slack, or Teams when query results cross a threshold or fail an expectation."
    supports_schedule = True
    supports_manual = True

    config_schema = {
        "type": "object",
        "required": ["conditions", "channels"],
        "properties": {
            "conditions": {
                "type": "array",
                "title": "Conditions",
                "description": "One or more conditions to evaluate. Alert fires when condition(s) fail.",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "required": ["type"],
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["row_count", "no_rows", "column_change_pct", "ai_expectation"],
                            "title": "Condition type",
                        },
                        "operator": {
                            "type": "string",
                            "enum": [">", ">=", "<", "<=", "==", "!="],
                            "title": "Operator",
                        },
                        "value": {
                            "type": "number",
                            "title": "Threshold value",
                        },
                        "column": {
                            "type": "string",
                            "title": "Column name",
                        },
                        "threshold_pct": {
                            "type": "number",
                            "title": "Change threshold (%)",
                            "minimum": 0,
                        },
                        "aggregate": {
                            "type": "string",
                            "enum": ["sum", "avg", "max", "min", "first"],
                            "default": "sum",
                            "title": "Aggregate function",
                        },
                        "prompt": {
                            "type": "string",
                            "title": "Expectation",
                            "description": "Plain English expectation. Example: 'All rows should have status = active'",
                        },
                    },
                },
            },
            "condition_mode": {
                "type": "string",
                "title": "Condition logic",
                "enum": ["any", "all"],
                "default": "any",
            },
            "alert_mode": {
                "type": "string",
                "title": "Alert frequency",
                "enum": ["every_run", "on_change"],
                "default": "on_change",
            },
            "resolution_mode": {
                "type": "string",
                "title": "Resolution",
                "enum": ["auto", "manual", "both"],
                "default": "auto",
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
                        },
                        "webhook_url": {
                            "type": "string",
                            "title": "Webhook URL",
                        },
                    },
                },
            },
            "severity": {
                "type": "string",
                "title": "Severity",
                "enum": ["info", "warning", "critical"],
                "default": "warning",
            },
            "message": {
                "type": "string",
                "title": "Custom alert message",
                "description": "Optional message included in all alert notifications.",
            },
        },
    }

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_config(self, config: Dict[str, Any]) -> List[str]:
        errors: List[str] = []

        conditions = config.get("conditions", [])
        if not conditions:
            errors.append("At least one condition is required.")

        for i, cond in enumerate(conditions):
            ctype = cond.get("type")
            if ctype == "row_count":
                if cond.get("operator") not in (">", ">=", "<", "<=", "==", "!="):
                    errors.append(f"Condition {i+1}: invalid operator.")
                if not isinstance(cond.get("value"), (int, float)):
                    errors.append(f"Condition {i+1}: threshold value must be a number.")
            elif ctype == "column_change_pct":
                if not cond.get("column"):
                    errors.append(f"Condition {i+1}: column name is required.")
                if not isinstance(cond.get("threshold_pct"), (int, float)):
                    errors.append(f"Condition {i+1}: threshold_pct must be a number.")
            elif ctype == "ai_expectation":
                if not cond.get("prompt", "").strip():
                    errors.append(f"Condition {i+1}: expectation prompt cannot be empty.")
            elif ctype != "no_rows":
                errors.append(f"Condition {i+1}: unknown type {ctype!r}.")

        channels = config.get("channels", [])
        if not channels:
            errors.append("At least one delivery channel is required.")
        for i, ch in enumerate(channels):
            ctype = ch.get("type")
            if ctype == "email" and not ch.get("recipients"):
                errors.append(f"Channel {i+1}: email channel requires at least one recipient.")
            elif ctype in ("slack", "teams") and not ch.get("webhook_url", "").strip():
                errors.append(f"Channel {i+1}: {ctype} channel requires a webhook URL.")
            elif ctype not in ("email", "slack", "teams"):
                errors.append(f"Channel {i+1}: unknown channel type {ctype!r}.")

        return errors

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(self, context: SkillContext) -> Dict[str, Any]:
        cfg = context.config

        # Load last alert state from the skill record
        last_state = self._load_last_state(context)

        # Evaluate all conditions
        evaluation = self._evaluate_conditions(context, cfg, last_state)
        conditions_failed = evaluation["failed"]
        all_passed = len(conditions_failed) == 0

        # Determine whether to alert based on alert_mode
        should_alert = self._should_alert(
            cfg=cfg,
            all_passed=all_passed,
            conditions_failed=conditions_failed,
            last_state=last_state,
            context=context,
        )

        # Persist new state
        new_state = {
            "all_passed": all_passed,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "failed_conditions": conditions_failed,
        }
        self._save_state(context, new_state)

        if not should_alert:
            return {
                "success": True,
                "message": "Conditions evaluated — no alert triggered.",
                "all_passed": all_passed,
                "conditions_failed": len(conditions_failed),
                "alerted": False,
            }

        # Build and deliver alert
        skill_name = self._get_skill_name(context)
        payload = self._build_payload(context, cfg, conditions_failed, skill_name)
        delivery_results = self._deliver(payload, cfg["channels"])

        any_delivered = any(r["success"] for r in delivery_results)
        return {
            "success": any_delivered,
            "message": f"Alert sent via {sum(r['success'] for r in delivery_results)}/{len(delivery_results)} channel(s).",
            "all_passed": all_passed,
            "conditions_failed": len(conditions_failed),
            "alerted": True,
            "delivery_results": delivery_results,
        }

    # ------------------------------------------------------------------
    # Condition evaluators
    # ------------------------------------------------------------------

    def _evaluate_conditions(
        self,
        context: SkillContext,
        cfg: Dict[str, Any],
        last_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Evaluate all conditions and return lists of failed and passed."""
        failed = []
        passed = []
        condition_mode = cfg.get("condition_mode", "any")
        row_count = context.metadata.row_count if context.metadata else len(context.results or context.rows)

        for cond in cfg.get("conditions", []):
            ctype = cond["type"]
            result = None

            if ctype == "row_count":
                result = self._eval_row_count(context, cond)
            elif ctype == "no_rows":
                result = self._eval_no_rows(context)
            elif ctype == "column_change_pct":
                result = self._eval_column_change_pct(context, cond, last_state)
            elif ctype == "ai_expectation":
                result = self._eval_ai_expectation(context, cond, row_count)

            if result:
                if result["passed"]:
                    passed.append(result)
                else:
                    failed.append(result)

        # Apply condition_mode logic
        if condition_mode == "all" and len(failed) < len(cfg.get("conditions", [])):
            # "all" mode: only counts as failure if ALL conditions fail
            return {"failed": [], "passed": passed + failed}

        return {"failed": failed, "passed": passed}

    def _eval_row_count(self, context: SkillContext, cond: Dict[str, Any]) -> Dict[str, Any]:
        row_count = context.metadata.row_count if context.metadata else len(context.rows or context.results)
        operator = cond["operator"]
        threshold = cond["value"]
        ops = {
            ">": row_count > threshold,
            ">=": row_count >= threshold,
            "<": row_count < threshold,
            "<=": row_count <= threshold,
            "==": row_count == threshold,
            "!=": row_count != threshold,
        }
        passed = not ops.get(operator, False)  # condition "fails" when threshold is crossed
        return {
            "type": "row_count",
            "passed": passed,
            "message": f"Row count is {row_count} (threshold: {operator} {threshold})",
            "value": row_count,
        }

    def _eval_no_rows(self, context: SkillContext) -> Dict[str, Any]:
        row_count = context.metadata.row_count if context.metadata else len(context.rows or context.results)
        passed = row_count > 0
        return {
            "type": "no_rows",
            "passed": passed,
            "message": "Query returned no rows." if not passed else "Query returned rows.",
            "value": row_count,
        }

    def _eval_column_change_pct(
        self,
        context: SkillContext,
        cond: Dict[str, Any],
        last_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        rows = context.results if context.results else context.rows
        column = cond["column"]
        threshold_pct = cond["threshold_pct"]
        aggregate = cond.get("aggregate", "sum")

        current_value = self._aggregate_column(rows, column, aggregate)

        # Get previous value from last state
        prev_values = last_state.get("column_values", {})
        prev_value = prev_values.get(f"{column}:{aggregate}")

        if prev_value is None or prev_value == 0:
            return {
                "type": "column_change_pct",
                "passed": True,
                "message": f"No previous value for {column} ({aggregate}) — baseline recorded.",
                "value": current_value,
                "prev_value": None,
                "change_pct": None,
            }

        change_pct = abs((current_value - prev_value) / prev_value) * 100
        passed = change_pct <= threshold_pct
        return {
            "type": "column_change_pct",
            "passed": passed,
            "message": (
                f"{column} ({aggregate}) changed by {change_pct:.1f}% "
                f"(threshold: {threshold_pct}%): {prev_value} → {current_value}"
            ),
            "value": current_value,
            "prev_value": prev_value,
            "change_pct": round(change_pct, 2),
        }

    def _eval_ai_expectation(
        self,
        context: SkillContext,
        cond: Dict[str, Any],
        row_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        if row_count is None:
            row_count = context.metadata.row_count if context.metadata else len(context.rows or context.results)
        prompt = cond["prompt"]

        # Seam: _get_workspace_config called locally since SkillContext has no workspace_config field
        from app.tasks.skill_runner import _get_workspace_config
        workspace_cfg = _get_workspace_config(context.workspace_id)
        llm_config = workspace_cfg.get("llm")

        if not llm_config:
            return {
                "type": "ai_expectation",
                "passed": True,
                "message": "AI expectation skipped — no LLM configured for workspace.",
            }

        try:
            verdict = self._call_llm_for_verdict(context, prompt, row_count)
            return {
                "type": "ai_expectation",
                "passed": verdict["passed"],
                "message": verdict.get("reason", prompt),
                "prompt": prompt,
            }
        except AI_EXPECTATION_FALLBACK_ERRORS as exc:
            logger.warning("AI expectation evaluation failed: %s", exc)
            return {
                "type": "ai_expectation",
                "passed": True,  # fail-open: don't alert if LLM is unavailable
                "message": f"AI evaluation unavailable: {exc}",
            }

    def _call_llm_for_verdict(
        self,
        context: SkillContext,
        prompt: str,
        row_count: int,
    ) -> Dict[str, Any]:
        """
        Call the workspace LLM to evaluate the expectation.
        Returns {"passed": bool, "reason": str}.

        Seam: build_llm_client_for_role → runtime.client.chat_json
        """
        from app.config.llm_resolver import build_llm_client_for_role
        from app.constants.llm_roles import LLMRole

        col_list = ", ".join((context.metadata.column_names if context.metadata else context.columns)[:10])
        sample = (context.results if context.results else context.rows)[:20]

        system_prompt = (
            "You are a data quality checker. Evaluate whether the provided query results "
            "meet the user's expectation. Respond ONLY with valid JSON in this exact format: "
            '{"passed": true|false, "reason": "one sentence explanation"}'
        )
        user_prompt = (
            f"Expectation: {prompt}\n\n"
            f"Columns: {col_list}\n"
            f"Row count: {row_count}\n"
            f"Sample data (first 20 rows):\n{json.dumps(sample, default=str)}"
        )

        runtime = build_llm_client_for_role(
            workspace_id=context.workspace_id,
            role=LLMRole.SUMMARIZER,
        )
        payload = runtime.client.chat_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_format=True,
            validator=lambda d: (
                isinstance(d, dict)
                and isinstance(d.get("passed"), bool)
                and isinstance(d.get("reason"), str)
            ),
            max_tokens=220,
        )
        passed = bool(payload["passed"])
        reason = str(payload["reason"]).strip()
        return {"passed": passed, "reason": reason}

    # ------------------------------------------------------------------
    # Alert state management (raw SQL — matches project convention)
    # ------------------------------------------------------------------

    def _should_alert(
        self,
        cfg: Dict[str, Any],
        all_passed: bool,
        conditions_failed: List[Dict],
        last_state: Dict[str, Any],
        context: SkillContext,
    ) -> bool:
        del conditions_failed
        alert_mode = cfg.get("alert_mode", "on_change")

        if all_passed:
            return False  # nothing failed — never alert

        if alert_mode == "every_run":
            return True

        # on_change mode: only alert if state changed from passing to failing
        was_passing = last_state.get("all_passed", True)  # default: assume was passing
        resolution_mode = cfg.get("resolution_mode", "auto")

        # Check manual acknowledgement
        if resolution_mode in ("manual", "both"):
            acknowledged_at = self._get_acknowledged_at(context)
            if acknowledged_at and not was_passing:
                # Already acknowledged — don't re-alert unless state changes again
                return False

        return was_passing  # alert only on transition from pass → fail

    def _load_last_state(self, context: SkillContext) -> Dict[str, Any]:
        """Load last alert state from the query_skills record."""
        try:
            from app.adapters.mysql_sql_executor import ForgeMetaSQL
            rows = ForgeMetaSQL().execute_query_mappings(
                "SELECT last_alert_state FROM query_skills WHERE id = :id LIMIT 1",
                {"id": context.skill_id},
            )
            if rows and rows[0].get("last_alert_state"):
                state = rows[0]["last_alert_state"]
                if isinstance(state, str):
                    state = json.loads(state)
                return state or {}
        except ALERT_STATE_FALLBACK_ERRORS as exc:
            logger.warning("Could not load last alert state for skill %s: %s", context.skill_id, exc)
        return {}

    def _save_state(self, context: SkillContext, state: Dict[str, Any]) -> None:
        """Persist alert state to query_skills.last_alert_state."""
        try:
            from app.adapters.mysql_sql_executor import ForgeMetaSQL
            existing = self._load_last_state(context)
            state["column_values"] = self._extract_column_values(context, existing)
            ForgeMetaSQL().execute_write(
                "UPDATE query_skills SET last_alert_state = :state WHERE id = :id",
                {"state": json.dumps(state), "id": context.skill_id},
            )
        except ALERT_STATE_FALLBACK_ERRORS as exc:
            logger.warning("Could not save alert state for skill %s: %s", context.skill_id, exc)

    def _get_acknowledged_at(self, context: SkillContext) -> Optional[datetime]:
        try:
            from app.adapters.mysql_sql_executor import ForgeMetaSQL
            rows = ForgeMetaSQL().execute_query_mappings(
                "SELECT alert_acknowledged_at FROM query_skills WHERE id = :id LIMIT 1",
                {"id": context.skill_id},
            )
            if rows and rows[0].get("alert_acknowledged_at"):
                return rows[0]["alert_acknowledged_at"]
        except ALERT_STATE_FALLBACK_ERRORS:
            logger.warning("Could not load alert acknowledgement for skill %s", context.skill_id)
        return None

    def _extract_column_values(
        self, context: SkillContext, existing_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build a snapshot of column aggregate values for change_pct tracking."""
        values = existing_state.get("column_values", {})
        rows = context.results if context.results else context.rows
        for cond in context.config.get("conditions", []):
            if cond.get("type") == "column_change_pct":
                col = cond["column"]
                agg = cond.get("aggregate", "sum")
                current = self._aggregate_column(rows, col, agg)
                if current is not None:
                    values[f"{col}:{agg}"] = current
        return values

    # ------------------------------------------------------------------
    # Delivery
    # ------------------------------------------------------------------

    def _deliver(
        self, payload: DeliveryPayload, channel_configs: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        results = []
        for ch_config in channel_configs:
            ch_type = ch_config.get("type")
            try:
                channel = get_channel(ch_type)
                success, message = channel.send(payload, ch_config)
                results.append({"channel": ch_type, "success": success, "message": message})
                logger.info("Alert delivery %s via %s: %s", "OK" if success else "FAIL", ch_type, message)
            except DELIVERY_FALLBACK_ERRORS as exc:
                results.append({"channel": ch_type, "success": False, "message": str(exc)})
        return results

    def _build_payload(
        self,
        context: SkillContext,
        cfg: Dict[str, Any],
        conditions_failed: List[Dict[str, Any]],
        skill_name: str,
    ) -> DeliveryPayload:
        custom_message = cfg.get("message", "")
        summary = custom_message or f"{len(conditions_failed)} condition(s) failed on '{skill_name}'"
        detail_lines = [f"• {c['message']}" for c in conditions_failed]
        detail_text = "\n".join([summary, "", *detail_lines])
        detail_html = self._build_alert_html(cfg, conditions_failed, skill_name, custom_message)

        return DeliveryPayload(
            subject=f"{skill_name} — Alert",
            summary=summary,
            detail_html=detail_html,
            detail_text=detail_text,
            query_name=skill_name,
            workspace_id=context.workspace_id,
            query_id=context.skill_id,
            conditions_failed=conditions_failed,
            severity=cfg.get("severity", "warning"),
        )

    def _build_alert_html(
        self,
        cfg: Dict[str, Any],
        conditions_failed: List[Dict[str, Any]],
        skill_name: str,
        custom_message: str,
    ) -> str:
        rows_html = "".join(
            f"<tr><td style='padding:6px 8px;border-bottom:1px solid #eee'>{c['type']}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #eee'>{c['message']}</td></tr>"
            for c in conditions_failed
        )
        custom_html = f"<p>{custom_message}</p>" if custom_message else ""
        severity = cfg.get("severity", "warning")
        color = {"info": "#0078d4", "warning": "#f7630c", "critical": "#d13438"}.get(severity, "#f7630c")

        return f"""
<div style="font-family:sans-serif;max-width:640px;margin:0 auto">
  <div style="border-left:4px solid {color};padding:12px 16px;background:#fafafa;margin-bottom:16px">
    <strong style="color:{color}">{severity.upper()}</strong>
    &nbsp;{skill_name}
  </div>
  {custom_html}
  <table style="width:100%;border-collapse:collapse;font-size:13px">
    <thead>
      <tr style="background:#f0f0f0">
        <th style="padding:6px 8px;text-align:left">Condition</th>
        <th style="padding:6px 8px;text-align:left">Detail</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
  <p style="color:#999;font-size:11px;margin-top:16px">
    QueryForge · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
  </p>
</div>
"""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_skill_name(self, context: SkillContext) -> str:
        """Look up the skill's name from the DB for use in alert messages."""
        try:
            from app.adapters.mysql_sql_executor import ForgeMetaSQL
            rows = ForgeMetaSQL().execute_query_mappings(
                "SELECT name FROM query_skills WHERE id = :id LIMIT 1",
                {"id": context.skill_id},
            )
            if rows and rows[0].get("name"):
                return str(rows[0]["name"])
        except ALERT_STATE_FALLBACK_ERRORS:
            logger.warning("Could not resolve skill name for skill %s", context.skill_id)
        return context.skill_id

    def _aggregate_column(
        self, rows: List[Dict[str, Any]], column: str, aggregate: str
    ) -> Optional[float]:
        values = []
        for row in rows:
            v = row.get(column)
            try:
                values.append(float(v))
            except (TypeError, ValueError):
                pass

        if not values:
            return None

        return {
            "sum": sum(values),
            "avg": sum(values) / len(values),
            "max": max(values),
            "min": min(values),
            "first": values[0],
        }.get(aggregate, sum(values))
