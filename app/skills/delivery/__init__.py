"""
app/skills/delivery/__init__.py

Delivery channel abstraction for the threshold alert skill.
Each channel implements send() — the alert skill loops over configured channels.

Supported channels:
  email   — reuses existing mailer
  slack   — Slack incoming webhook (Block Kit)
  teams   — Microsoft Teams incoming webhook (Adaptive Card)
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from urllib import request as urllib_request
from urllib.error import URLError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


@dataclass
class DeliveryPayload:
    """Normalised alert payload passed to every channel."""
    subject: str
    summary: str                  # short one-liner for notification previews
    detail_html: str              # full HTML body (used by email)
    detail_text: str              # plain text fallback (used by Slack/Teams)
    query_name: str
    workspace_id: int
    query_id: int
    conditions_failed: list[dict] # list of {type, message} for each failed condition
    severity: str = "warning"     # "info" | "warning" | "critical"


class BaseDeliveryChannel(ABC):
    channel_type: str

    @abstractmethod
    def send(self, payload: DeliveryPayload, config: dict[str, Any]) -> tuple[bool, str]:
        """
        Send the alert. Returns (success: bool, message: str).
        Must not raise — catch and return (False, error_message).
        """


# ---------------------------------------------------------------------------
# Email channel
# ---------------------------------------------------------------------------


class EmailDeliveryChannel(BaseDeliveryChannel):
    channel_type = "email"

    def send(self, payload: DeliveryPayload, config: dict[str, Any]) -> tuple[bool, str]:
        recipients = config.get("recipients", [])
        if not recipients:
            return False, "No recipients configured."

        try:
            from app.email.mailer import send_email, get_logo

            logo_path = get_logo()
            subject = f"[QueryForge Alert] {payload.subject}"

            for recipient in recipients:
                send_email(
                    logo_path=logo_path,
                    subject=subject,
                    to_email=recipient,
                    html=payload.detail_html,
                    attachments=None,
                    reply_to=None,
                )

            return True, f"Alert emailed to {len(recipients)} recipient(s)."
        except Exception as exc:
            logger.exception("Email alert delivery failed")
            return False, str(exc)


# ---------------------------------------------------------------------------
# Slack channel
# ---------------------------------------------------------------------------


class SlackDeliveryChannel(BaseDeliveryChannel):
    channel_type = "slack"

    def send(self, payload: DeliveryPayload, config: dict[str, Any]) -> tuple[bool, str]:
        webhook_url = config.get("webhook_url", "").strip()
        if not webhook_url:
            return False, "No Slack webhook URL configured."

        severity_emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(
            payload.severity, "⚠️"
        )

        # Build Slack Block Kit message
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{severity_emoji} {payload.subject}",
                },
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": payload.detail_text},
            },
        ]

        if payload.conditions_failed:
            condition_lines = "\n".join(
                f"• {c['message']}" for c in payload.conditions_failed
            )
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Failed conditions:*\n{condition_lines}",
                },
            })

        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"QueryForge · {payload.query_name}",
                }
            ],
        })

        return self._post_webhook(webhook_url, {"blocks": blocks})

    def _post_webhook(self, url: str, body: dict) -> tuple[bool, str]:
        try:
            data = json.dumps(body).encode("utf-8")
            req = urllib_request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib_request.urlopen(req, timeout=10) as resp:
                response_text = resp.read().decode()
                if resp.status == 200 and response_text == "ok":
                    return True, "Slack alert delivered."
                return False, f"Slack responded: {resp.status} {response_text}"
        except URLError as exc:
            logger.error("Slack webhook failed: %s", exc)
            return False, f"Slack webhook error: {exc}"
        except Exception as exc:
            logger.exception("Slack delivery unexpected error")
            return False, str(exc)


# ---------------------------------------------------------------------------
# Microsoft Teams channel
# ---------------------------------------------------------------------------


class TeamsDeliveryChannel(BaseDeliveryChannel):
    channel_type = "teams"

    def send(self, payload: DeliveryPayload, config: dict[str, Any]) -> tuple[bool, str]:
        webhook_url = config.get("webhook_url", "").strip()
        if not webhook_url:
            return False, "No Teams webhook URL configured."

        severity_color = {
            "info": "0078D4",     # Teams blue
            "warning": "F7630C",  # Teams orange
            "critical": "D13438", # Teams red
        }.get(payload.severity, "F7630C")

        # Build Teams Adaptive Card
        card = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.4",
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": payload.subject,
                                "weight": "Bolder",
                                "size": "Medium",
                                "color": "Warning" if payload.severity == "warning" else "Attention",
                            },
                            {
                                "type": "TextBlock",
                                "text": payload.detail_text,
                                "wrap": True,
                            },
                            *self._condition_facts(payload.conditions_failed),
                            {
                                "type": "TextBlock",
                                "text": f"Query: {payload.query_name}",
                                "size": "Small",
                                "isSubtle": True,
                            },
                        ],
                        "msteams": {"width": "Full"},
                    },
                }
            ],
        }

        return self._post_webhook(webhook_url, card, severity_color)

    def _condition_facts(self, conditions: list[dict]) -> list[dict]:
        if not conditions:
            return []
        return [
            {
                "type": "FactSet",
                "facts": [
                    {"title": f"Condition {i+1}", "value": c["message"]}
                    for i, c in enumerate(conditions)
                ],
            }
        ]

    def _post_webhook(
        self, url: str, body: dict, color: str = "F7630C"
    ) -> tuple[bool, str]:
        try:
            data = json.dumps(body).encode("utf-8")
            req = urllib_request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib_request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 202):
                    return True, "Teams alert delivered."
                response_text = resp.read().decode()
                return False, f"Teams responded: {resp.status} {response_text}"
        except URLError as exc:
            logger.error("Teams webhook failed: %s", exc)
            return False, f"Teams webhook error: {exc}"
        except Exception as exc:
            logger.exception("Teams delivery unexpected error")
            return False, str(exc)


# ---------------------------------------------------------------------------
# Channel registry
# ---------------------------------------------------------------------------


CHANNEL_REGISTRY: dict[str, type[BaseDeliveryChannel]] = {
    "email": EmailDeliveryChannel,
    "slack": SlackDeliveryChannel,
    "teams": TeamsDeliveryChannel,
}


def get_channel(channel_type: str) -> BaseDeliveryChannel:
    if channel_type not in CHANNEL_REGISTRY:
        raise ValueError(
            f"Unknown delivery channel: {channel_type!r}. "
            f"Available: {list(CHANNEL_REGISTRY)}"
        )
    return CHANNEL_REGISTRY[channel_type]()
