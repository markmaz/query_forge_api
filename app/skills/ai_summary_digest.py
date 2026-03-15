"""
app/skills/ai_summary_digest.py

AI Summary Digest skill — runs a query, sends results to the workspace LLM,
and delivers a narrative summary via email.

Triggers:
  - Schedule (cron)
  - Manual
  - Post-alert (when triggered_by="alert" from threshold_alert)

Includes:
  - LLM narrative summary
  - Key metrics / highlights (extracted by LLM)
  - Comparison to previous run (stored in last_digest_snapshot)
  - Optional raw data table as appendix

The LLM receives the full prompt in one call and returns structured JSON:
  {
    "narrative": "...",
    "highlights": ["...", "..."],
    "comparison": "..."   # null if no previous snapshot
  }
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from html import escape as _escape

from app.skills.base import BaseSkill, SkillContext, SkillResult
from app.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


@SkillRegistry.register
class AISummaryDigestSkill(BaseSkill):
    skill_type = "ai_summary_digest"
    display_name = "AI Summary Digest"
    description = "Send an AI-generated narrative summary of query results via email."
    supports_schedule = True
    supports_manual = True

    config_schema = {
        "type": "object",
        "required": ["recipients", "subject"],
        "properties": {
            "recipients": {
                "type": "array",
                "title": "Recipients",
                "items": {"type": "string", "format": "email"},
                "minItems": 1,
                "ui:widget": "email-list",
            },
            "subject": {
                "type": "string",
                "title": "Subject",
                "description": "Supports {{query_name}}, {{date}} tokens.",
                "default": "{{query_name}} — Weekly Digest {{date}}",
                "ui:widget": "text",
            },
            "prompt_hint": {
                "type": "string",
                "title": "Summary guidance",
                "description": "Optional context to guide the AI. Example: 'Focus on week-over-week revenue changes.'",
                "ui:widget": "textarea",
            },
            "include_comparison": {
                "type": "boolean",
                "title": "Compare to previous run",
                "description": "Include a comparison to the last time this digest ran.",
                "default": True,
                "ui:widget": "checkbox",
            },
            "include_appendix": {
                "type": "boolean",
                "title": "Include raw data table",
                "description": "Append a formatted data table after the summary.",
                "default": False,
                "ui:widget": "checkbox",
            },
            "max_rows": {
                "type": "integer",
                "title": "Max rows in appendix",
                "default": 100,
                "minimum": 1,
                "maximum": 1000,
                "ui:widget": "number",
                "ui:condition": {"property": "include_appendix", "enum": [True]},
            },
            "include_query_link": {
                "type": "boolean",
                "title": "Include link to query",
                "default": True,
                "ui:widget": "checkbox",
            },
            "llm_role": {
                "type": "string",
                "title": "LLM role",
                "description": "Workspace LLM role to use for summarisation.",
                "default": "summarizer",
                "ui:widget": "text",
            },
        },
        "additionalProperties": False,
    }

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if not config.get("recipients"):
            errors.append("At least one recipient is required.")
        for addr in config.get("recipients", []):
            if "@" not in addr or "." not in addr.split("@")[-1]:
                errors.append(f"Invalid email address: {addr!r}")
        if not config.get("subject", "").strip():
            errors.append("Subject cannot be empty.")
        return errors

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(self, context: SkillContext) -> SkillResult:
        cfg = context.config

        # Load previous snapshot for comparison
        previous_snapshot = self._load_snapshot(context) if cfg.get("include_comparison", True) else None

        # Generate AI digest
        try:
            digest = self._generate_digest(context, cfg, previous_snapshot)
        except Exception as exc:
            logger.exception("AI digest generation failed for query %s", context.query_id)
            return SkillResult(success=False, message="AI digest generation failed.", error=str(exc))

        # Build and send email
        subject = self._render_subject(cfg["subject"], context)
        html_body = self._build_email_body(context, cfg, digest)

        try:
            self._send(cfg["recipients"], subject, html_body)
        except Exception as exc:
            logger.exception("Digest email delivery failed")
            return SkillResult(success=False, message="Email delivery failed.", error=str(exc))

        # Save snapshot for next comparison
        self._save_snapshot(context, digest)

        return SkillResult(
            success=True,
            message=f"Digest delivered to {len(cfg['recipients'])} recipient(s).",
            data={
                "recipients": cfg["recipients"],
                "row_count": context.metadata.row_count,
                "subject": subject,
                "had_previous_snapshot": previous_snapshot is not None,
            },
        )

    # ------------------------------------------------------------------
    # LLM digest generation
    # ------------------------------------------------------------------

    def _generate_digest(
        self,
        context: SkillContext,
        cfg: dict,
        previous_snapshot: dict | None,
    ) -> dict:
        """
        Call the workspace LLM and return structured digest:
        {
            "narrative": str,
            "highlights": list[str],
            "comparison": str | None
        }
        """
        llm_config = context.workspace_config.get("llm")
        if not llm_config:
            return self._fallback_digest(context)

        system_prompt = self._build_system_prompt(cfg, previous_snapshot)
        user_prompt = self._build_user_prompt(context, cfg, previous_snapshot)

        try:
            from app.config.llm_resolver import build_llm_client_for_role
            from app.constants.llm_roles import LLMRole

            # Resolve role — fall back to SUMMARIZER, then default
            role_name = cfg.get("llm_role", "summarizer").upper()
            role = getattr(LLMRole, role_name, LLMRole.SUMMARIZER)

            runtime = build_llm_client_for_role(
                workspace_id=context.workspace_id,
                role=role,
            )
            result = runtime.client.chat_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format=True,
                validator=lambda d: (
                    isinstance(d, dict)
                    and isinstance(d.get("narrative"), str)
                    and isinstance(d.get("highlights"), list)
                ),
                max_tokens=800,
            )
            return {
                "narrative": result.get("narrative", ""),
                "highlights": result.get("highlights", []),
                "comparison": result.get("comparison"),
            }
        except Exception as exc:
            logger.warning("LLM digest failed, using fallback: %s", exc)
            return self._fallback_digest(context)

    def _build_system_prompt(self, cfg: dict, previous_snapshot: dict | None) -> str:
        hint = cfg.get("prompt_hint", "")
        hint_line = f"\nAdditional guidance: {hint}" if hint else ""
        comparison_instruction = (
            '\n- "comparison": one sentence comparing to the previous run (key changes, trends)'
            if previous_snapshot else
            '\n- "comparison": null (no previous data available)'
        )
        return (
            f"You are a data analyst writing a concise business digest. "
            f"Analyse the query results and respond ONLY with valid JSON in this exact format:\n"
            f'{{"narrative": "2-4 paragraph summary", '
            f'"highlights": ["key insight 1", "key insight 2", "key insight 3"],'
            f'"comparison": "comparison sentence or null"}}\n'
            f"Rules:\n"
            f"- narrative: 2-4 concise paragraphs for a business audience\n"
            f"- highlights: exactly 3-5 bullet points, each under 15 words\n"
            f"{comparison_instruction}"
            f"{hint_line}"
        )

    def _build_user_prompt(
        self,
        context: SkillContext,
        cfg: dict,
        previous_snapshot: dict | None,
    ) -> str:
        col_list = ", ".join(context.metadata.column_names[:15])
        sample = context.results[:30]
        prev_section = ""
        if previous_snapshot:
            prev_date = previous_snapshot.get("executed_at", "previous run")
            prev_highlights = previous_snapshot.get("highlights", [])
            prev_section = (
                f"\nPrevious run ({prev_date}) highlights:\n"
                + "\n".join(f"- {h}" for h in prev_highlights)
            )

        return (
            f"Query: {context.metadata.query_name}\n"
            f"Columns: {col_list}\n"
            f"Total rows: {context.metadata.row_count}\n"
            f"Sample data (first 30 rows):\n{json.dumps(sample, default=str)}"
            f"{prev_section}"
        )

    def _fallback_digest(self, context: SkillContext) -> dict:
        """Minimal digest when no LLM is configured."""
        return {
            "narrative": (
                f"Query '{context.metadata.query_name}' returned "
                f"{context.metadata.row_count} row(s). "
                f"Configure a workspace LLM to generate AI summaries."
            ),
            "highlights": [f"{context.metadata.row_count} rows returned"],
            "comparison": None,
        }

    # ------------------------------------------------------------------
    # Email body builder
    # ------------------------------------------------------------------

    def _build_email_body(
        self,
        context: SkillContext,
        cfg: dict,
        digest: dict,
    ) -> str:
        parts = [self._header(context)]

        # Highlights
        if digest.get("highlights"):
            highlights_html = "".join(
                f"<li style='margin-bottom:4px'>{_escape(h)}</li>"
                for h in digest["highlights"]
            )
            parts.append(f"""
<div style="background:#f8f9fa;border-left:3px solid #4f6ef7;padding:12px 16px;margin-bottom:16px;border-radius:0 6px 6px 0">
  <strong style="font-size:12px;text-transform:uppercase;color:#888;letter-spacing:.5px">Highlights</strong>
  <ul style="margin:8px 0 0;padding-left:18px;font-size:13px">{highlights_html}</ul>
</div>""")

        # Narrative
        if digest.get("narrative"):
            narrative_paragraphs = "".join(
                f"<p style='margin:0 0 12px;font-size:14px;line-height:1.6'>{_escape(p)}</p>"
                for p in digest["narrative"].split("\n\n")
                if p.strip()
            )
            parts.append(f'<div style="margin-bottom:16px">{narrative_paragraphs}</div>')

        # Comparison
        if digest.get("comparison"):
            parts.append(f"""
<div style="border:1px solid #e5e7eb;border-radius:6px;padding:10px 14px;margin-bottom:16px;font-size:13px;color:#555">
  <strong>vs previous run:</strong> {_escape(digest["comparison"])}
</div>""")

        # Query link
        if cfg.get("include_query_link", True):
            parts.append(self._query_link(context))

        # Raw data appendix
        if cfg.get("include_appendix", False) and context.results:
            max_rows = cfg.get("max_rows", 100)
            rows = context.results[:max_rows]
            parts.append(self._build_table(rows, context))

        parts.append(self._footer())
        return "\n".join(parts)

    def _build_table(self, rows: list[dict], context: SkillContext) -> str:
        cols = context.metadata.column_names or list(rows[0].keys())
        header = "".join(f"<th style='padding:6px 8px;background:#f0f0f0;text-align:left;font-size:12px'>{_escape(c)}</th>" for c in cols)
        body = "".join(
            "<tr>" + "".join(
                f"<td style='padding:5px 8px;border-bottom:1px solid #f0f0f0;font-size:12px'>{_escape(str(row.get(c, '')))}</td>"
                for c in cols
            ) + "</tr>"
            for row in rows
        )
        return f"""
<details style="margin-top:16px">
  <summary style="cursor:pointer;font-size:12px;color:#888;user-select:none">
    Raw data ({len(rows)} rows)
  </summary>
  <div style="overflow-x:auto;margin-top:8px">
    <table style="border-collapse:collapse;width:100%;font-family:sans-serif">
      <thead><tr>{header}</tr></thead>
      <tbody>{body}</tbody>
    </table>
  </div>
</details>"""

    # ------------------------------------------------------------------
    # Snapshot persistence (for comparison)
    # ------------------------------------------------------------------

    def _load_snapshot(self, context: SkillContext) -> dict | None:
        try:
            from app.models.skills import QuerySkill
            skill = QuerySkill.query.filter_by(
                query_id=context.query_id,
                workspace_id=context.workspace_id,
                skill_type=self.skill_type,
            ).first()
            return skill.last_alert_state if skill and skill.last_alert_state else None
        except Exception as exc:
            logger.warning("Could not load digest snapshot: %s", exc)
            return None

    def _save_snapshot(self, context: SkillContext, digest: dict) -> None:
        try:
            from app.extensions import db
            from app.models.skills import QuerySkill
            skill = QuerySkill.query.filter_by(
                query_id=context.query_id,
                workspace_id=context.workspace_id,
                skill_type=self.skill_type,
            ).first()
            if skill:
                skill.last_alert_state = {
                    "narrative": digest.get("narrative", ""),
                    "highlights": digest.get("highlights", []),
                    "executed_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "row_count": context.metadata.row_count,
                }
                db.session.add(skill)
                db.session.commit()
        except Exception as exc:
            logger.warning("Could not save digest snapshot: %s", exc)

    # ------------------------------------------------------------------
    # Helpers — reuse email delivery patterns
    # ------------------------------------------------------------------

    def _render_subject(self, template: str, context: SkillContext) -> str:
        return (
            template
            .replace("{{query_name}}", context.metadata.query_name)
            .replace("{{date}}", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        )

    def _send(self, recipients: list[str], subject: str, html: str) -> None:
        from app.email.mailer import get_logo, send_email
        logo_path = get_logo()
        for recipient in recipients:
            send_email(
                logo_path=logo_path,
                subject=subject,
                to_email=recipient,
                html=html,
            )

    def _header(self, context: SkillContext) -> str:
        return f"""
<div style="font-family:sans-serif;max-width:680px;margin:0 auto">
<p style="color:#888;font-size:12px;border-bottom:1px solid #eee;padding-bottom:8px;margin-bottom:16px">
  <strong>QueryForge Digest</strong> · {context.metadata.query_name}
  · {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
</p>"""

    def _footer(self) -> str:
        return """
<p style="color:#bbb;font-size:11px;margin-top:24px;border-top:1px solid #eee;padding-top:8px">
  Sent by QueryForge · Edit this digest in your workspace skills settings.
</p></div>"""

    def _query_link(self, context: SkillContext) -> str:
        from flask import current_app
        base_url = current_app.config.get("FRONTEND_BASE_URL", "")
        url = f"{base_url}/workspace/{context.workspace_id}/query/{context.query_id}"
        return f'<p><a href="{url}" style="color:#4f6ef7;font-size:13px">View query in QueryForge →</a></p>'
