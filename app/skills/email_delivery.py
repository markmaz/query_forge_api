from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from flask import current_app

from app.skills.base import BaseSkill, SkillContext
from app.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a data analyst summarizing query results for a business audience. "
    "Return a JSON object with a single key 'summary' containing 1-3 sentences that "
    "describe the key insights from the data."
)


@SkillRegistry.register
class EmailDeliverySkill(BaseSkill):
    skill_type = "email_delivery"

    def execute(self, context: SkillContext) -> Dict[str, Any]:
        from app.email.mailer import get_logo, send_email

        cfg = context.config or {}
        recipients: List[str] = list(cfg.get("recipients") or [])
        subject: str = str(cfg.get("subject") or "QueryForge Report")
        reply_to: Optional[str] = cfg.get("reply_to") or None
        include_summary: bool = bool(cfg.get("include_summary", True))

        summary_text = ""
        if include_summary and context.rows:
            summary_text = self._generate_summary(context)

        base_url = current_app.config.get("FRONTEND_BASE_URL", "http://localhost:3000")
        html = self._build_html(subject, summary_text, context.rows, context.columns, base_url)
        logo_path = get_logo()

        sent_count = 0
        failed: List[str] = []
        for recipient in recipients:
            try:
                send_email(
                    logo_path=logo_path,
                    subject=subject,
                    to_email=recipient,
                    html=html,
                    reply_to=reply_to,
                )
                sent_count += 1
            except Exception:
                logger.exception("EmailDeliverySkill: failed to send to %s", recipient)
                failed.append(recipient)

        return {
            "recipients_total": len(recipients),
            "sent": sent_count,
            "failed": failed,
        }

    def _generate_summary(self, context: SkillContext) -> str:
        try:
            from app.config.llm_resolver import build_llm_client_for_role

            runtime = build_llm_client_for_role(
                workspace_id=context.workspace_id,
                role="summarizer",
            )
            llm = runtime.client
            col_names = [str(c) for c in (context.columns or [])]
            user_prompt = (
                f"Columns: {', '.join(col_names)}\n"
                f"Row count: {len(context.rows)}\n"
                f"Sample rows (up to 10): {context.rows[:10]}"
            )
            payload = llm.chat_json(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                response_format=True,
                validator=lambda d: isinstance(d, dict) and isinstance(d.get("summary"), str),
                max_tokens=300,
            )
            return payload["summary"].strip()
        except Exception:
            logger.exception("EmailDeliverySkill: LLM summary generation failed")
            return ""

    def _build_html(
        self,
        title: str,
        summary: str,
        rows: List[Dict[str, Any]],
        columns: List[Any],
        base_url: str,
    ) -> str:
        col_labels = [str(c) for c in (columns or [])]
        summary_block = f"<p style='color:#555'>{summary}</p>" if summary else ""
        headers = "".join(
            f"<th style='padding:6px 12px;border-bottom:1px solid #ddd;text-align:left'>{col}</th>"
            for col in col_labels
        )
        body_rows = ""
        for row in rows[:200]:
            cells = "".join(
                f"<td style='padding:6px 12px;border-bottom:1px solid #eee'>{row.get(col, '') if isinstance(row, dict) else ''}</td>"
                for col in col_labels
            )
            body_rows += f"<tr>{cells}</tr>"

        query_url = f"{base_url.rstrip('/')}/query-studio"
        return (
            "<html><body style='font-family:sans-serif;max-width:900px;margin:0 auto;padding:20px'>"
            f"<h2 style='color:#1a1a2e'>{title}</h2>"
            f"{summary_block}"
            "<table style='width:100%;border-collapse:collapse;font-size:13px'>"
            f"<thead><tr style='background:#f5f5f5'>{headers}</tr></thead>"
            f"<tbody>{body_rows}</tbody>"
            "</table>"
            f"<p style='margin-top:20px;font-size:12px;color:#999'>"
            f"<a href='{query_url}'>View in QueryForge</a></p>"
            "</body></html>"
        )
