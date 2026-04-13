"""
app/skills/webhook_delivery.py

Webhook Delivery skill — sends query results to Slack or Microsoft Teams
on a schedule or manual trigger.

Reuses the existing delivery channel package (SlackDeliveryChannel,
TeamsDeliveryChannel) as the transport layer. The skill handles formatting
the query results into a meaningful payload and delegates sending.

Supported channels: slack, teams
Each skill instance targets ONE channel. To send to both, attach two skills.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.exceptions.forge_error import ForgeError
from app.skills.base import BaseSkill, SkillContext, SkillResult
from app.skills.delivery import DeliveryPayload, get_channel
from app.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

WEBHOOK_EXECUTION_FALLBACK_ERRORS = (ForgeError, OSError, RuntimeError, TypeError, ValueError, SQLAlchemyError)
EMAIL_HTML_FALLBACK_ERRORS = (ImportError, RuntimeError, TypeError, ValueError)
HIGHLIGHT_FALLBACK_ERRORS = (ForgeError, OSError, RuntimeError, TypeError, ValueError)


@SkillRegistry.register
class WebhookDeliverySkill(BaseSkill):
    skill_type = "webhook_delivery"
    display_name = "Webhook Delivery"
    description = "Send query results to Slack or Microsoft Teams on a schedule."
    supports_schedule = True
    supports_manual = True

    config_schema = {
        "type": "object",
        "required": ["channel_type"],
        "properties": {
            "channel_type": {
                "type": "string",
                "title": "Channel",
                "enum": ["slack", "teams", "webhook"],
                "enumNames": ["Slack", "Microsoft Teams", "Generic Webhook"],
                "ui:widget": "select",
            },
            "webhook_url": {
                "type": "string",
                "title": "Webhook URL",
                "description": "Incoming webhook URL from Slack or Teams, or a generic endpoint URL.",
                "ui:widget": "text",
            },
            "message": {
                "type": "string",
                "title": "Message",
                "description": "Optional message to include. Supports {{query_name}}, {{row_count}}, {{date}}.",
                "ui:widget": "textarea",
            },
            "format": {
                "type": "string",
                "title": "Format",
                "enum": ["summary", "table", "highlights"],
                "enumNames": [
                    "Summary — row count + key stats",
                    "Table — first N rows formatted",
                    "Highlights — AI-extracted key points",
                ],
                "default": "summary",
                "ui:widget": "select",
            },
            "max_rows": {
                "type": "integer",
                "title": "Max rows (table format)",
                "default": 10,
                "minimum": 1,
                "maximum": 50,
                "ui:widget": "number",
                "ui:condition": {"property": "format", "enum": ["table"]},
            },
            "send_if_empty": {
                "type": "boolean",
                "title": "Send even when results are empty",
                "default": False,
                "ui:widget": "checkbox",
            },
            "severity": {
                "type": "string",
                "title": "Severity",
                "enum": ["info", "warning", "critical"],
                "default": "info",
                "ui:widget": "select",
            },
        },
        "additionalProperties": False,
    }

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if config.get("channel_type") not in ("slack", "teams", "webhook"):
            errors.append("channel_type must be 'slack', 'teams', or 'webhook'.")
        destination_id = config.get("destination_id")
        target_url = str(config.get("webhook_url") or config.get("url") or "").strip()
        if not destination_id and not target_url:
            errors.append("Webhook URL or destination is required.")
        if config.get("format") not in ("summary", "table", "highlights"):
            errors.append("Format must be one of: summary, table, highlights.")
        return errors

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(self, context: SkillContext) -> SkillResult:
        cfg = context.config

        if not context.results and not cfg.get("send_if_empty", False):
            return SkillResult(
                success=True,
                message="No rows returned — webhook skipped (send_if_empty=False).",
                data={"skipped": True, "row_count": 0},
            )

        fmt = cfg.get("format", "summary")
        detail_text = self._build_detail_text(context, cfg, fmt)
        subject = self._render_tokens(
            cfg.get("message") or f"{context.metadata.query_name} — {context.metadata.row_count} rows",
            context,
        )

        payload = DeliveryPayload(
            subject=subject,
            summary=subject,
            detail_html=self._build_email_html(context, subject),
            detail_text=detail_text,
            query_name=context.metadata.query_name,
            workspace_id=context.workspace_id,
            query_id=context.query_id,
            conditions_failed=[],  # not an alert — no failed conditions
            severity=cfg.get("severity", "info"),
        )

        try:
            channels = cfg.get("channels")
            if isinstance(channels, list) and channels:
                results: list[dict[str, Any]] = []
                for raw_channel in channels:
                    if not isinstance(raw_channel, dict):
                        continue
                    channel_type = str(raw_channel.get("type") or "").strip().lower()
                    if not channel_type:
                        continue
                    channel = get_channel(channel_type)
                    success, message = channel.send(payload, raw_channel)
                    results.append({
                        "type": channel_type,
                        "success": success,
                        "message": message,
                    })
                overall_success = bool(results) and all(item["success"] for item in results)
                message = "; ".join(
                    f"{item['type']}: {item['message']}"
                    for item in results
                ) or "No delivery channels configured."
                return SkillResult(
                    success=overall_success,
                    message=message,
                    data={
                        "row_count": context.metadata.row_count,
                        "format": fmt,
                        "channels": results,
                    },
                    error=None if overall_success else message,
                )

            channel_config = self._channel_config(cfg)
            channel = get_channel(cfg["channel_type"])
            success, message = channel.send(payload, channel_config)
        except WEBHOOK_EXECUTION_FALLBACK_ERRORS as exc:
            logger.exception("Webhook delivery failed")
            return SkillResult(success=False, message="Webhook delivery failed.", error=str(exc))

        return SkillResult(
            success=success,
            message=message,
            data={
                "channel_type": cfg["channel_type"],
                "row_count": context.metadata.row_count,
                "format": fmt,
            },
            error=None if success else message,
        )

    def _build_email_html(self, context: SkillContext, subject: str) -> str:
        try:
            from flask import current_app
            from app.skills.email_delivery import EmailDeliverySkill

            base_url = current_app.config.get("FRONTEND_BASE_URL", "http://localhost:3000")
            return EmailDeliverySkill()._build_html(
                subject,
                "",
                context.rows,
                context.columns,
                base_url,
            )
        except EMAIL_HTML_FALLBACK_ERRORS:
            logger.exception("Failed to build email HTML for webhook delivery")
            return ""

    # ------------------------------------------------------------------
    # Formatters
    # ------------------------------------------------------------------

    def _build_detail_text(
        self,
        context: SkillContext,
        cfg: dict,
        fmt: str,
    ) -> str:
        if fmt == "summary":
            return self._format_summary(context)
        elif fmt == "table":
            return self._format_table(context, cfg.get("max_rows", 10))
        elif fmt == "highlights":
            return self._format_highlights(context, cfg)
        return self._format_summary(context)

    def _format_summary(self, context: SkillContext) -> str:
        rows = context.results
        if not rows:
            return f"*{context.metadata.query_name}* returned no results."

        cols = context.metadata.column_names or list(rows[0].keys())
        # Build a simple stats summary for numeric columns
        stats_lines = []
        for col in cols[:5]:
            values = []
            for row in rows:
                try:
                    values.append(float(row.get(col, 0)))
                except (TypeError, ValueError):
                    pass
            if values:
                stats_lines.append(
                    f"• *{col}*: {min(values):,.0f} – {max(values):,.0f} "
                    f"(avg {sum(values)/len(values):,.1f})"
                )

        stats_block = "\n".join(stats_lines) if stats_lines else ""
        return (
            f"*{context.metadata.query_name}*\n"
            f"{context.metadata.row_count} rows · "
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
            + (f"\n{stats_block}" if stats_block else "")
        )

    def _format_table(self, context: SkillContext, max_rows: int) -> str:
        rows = context.results[:max_rows]
        if not rows:
            return "No results."

        cols = context.metadata.column_names or list(rows[0].keys())

        # Build a plain-text table suitable for Slack/Teams code blocks
        col_widths = {col: max(len(col), max(len(str(row.get(col, ""))) for row in rows)) for col in cols}
        header = " | ".join(col.ljust(col_widths[col]) for col in cols)
        divider = "-+-".join("-" * col_widths[col] for col in cols)
        data_rows = "\n".join(
            " | ".join(str(row.get(col, "")).ljust(col_widths[col]) for col in cols)
            for row in rows
        )
        table = f"```\n{header}\n{divider}\n{data_rows}\n```"

        suffix = (
            f"\n_{context.metadata.row_count - max_rows} more rows not shown_"
            if context.metadata.row_count > max_rows else ""
        )
        return f"*{context.metadata.query_name}*\n{table}{suffix}"

    def _format_highlights(self, context: SkillContext, cfg: dict) -> str:
        """
        Use workspace LLM to extract 3-5 highlights from the results.
        Falls back to summary format if no LLM is configured.
        """
        del cfg
        llm_config = context.workspace_config.get("llm")
        if not llm_config:
            return self._format_summary(context)

        try:
            from app.config.llm_resolver import build_llm_client_for_role
            from app.constants.llm_roles import LLMRole

            role = getattr(LLMRole, "SUMMARIZER", LLMRole.SUMMARIZER)
            runtime = build_llm_client_for_role(
                workspace_id=context.workspace_id,
                role=role,
            )
            result = runtime.client.chat_json(
                system_prompt=(
                    "Extract 3-5 key highlights from the query results. "
                    'Respond ONLY with JSON: {"highlights": ["...", "..."]}'
                ),
                user_prompt=(
                    f"Query: {context.metadata.query_name}\n"
                    f"Rows: {context.metadata.row_count}\n"
                    f"Sample: {context.results[:20]}"
                ),
                response_format=True,
                validator=lambda d: isinstance(d, dict) and isinstance(d.get("highlights"), list),
                max_tokens=300,
            )
            lines = "\n".join(f"• {h}" for h in result.get("highlights", []))
            return f"*{context.metadata.query_name}*\n{lines}"
        except HIGHLIGHT_FALLBACK_ERRORS as exc:
            logger.warning("LLM highlights failed, using summary: %s", exc)
            return self._format_summary(context)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _channel_config(self, config: dict[str, Any]) -> dict[str, Any]:
        channel_type = str(config.get("channel_type") or "slack").strip().lower() or "slack"
        channel_config: dict[str, Any] = {"type": channel_type}
        destination_id = config.get("destination_id")
        if destination_id:
            channel_config["destination_id"] = destination_id
            return channel_config

        target_url = str(config.get("webhook_url") or config.get("url") or "").strip()
        if channel_type == "webhook":
            channel_config["url"] = target_url
            channel_config["method"] = str(config.get("method") or "POST").strip().upper() or "POST"
            headers = config.get("headers")
            if isinstance(headers, dict) and headers:
                channel_config["headers"] = headers
            auth_token = str(config.get("auth_token") or "").strip()
            if auth_token:
                channel_config["auth_token"] = auth_token
        else:
            channel_config["webhook_url"] = target_url
        return channel_config

    def _render_tokens(self, template: str, context: SkillContext) -> str:
        return (
            template
            .replace("{{query_name}}", context.metadata.query_name)
            .replace("{{row_count}}", str(context.metadata.row_count))
            .replace("{{date}}", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        )
