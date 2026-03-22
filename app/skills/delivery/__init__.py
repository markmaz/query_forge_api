"""
app/skills/delivery/__init__.py  — UPDATED for v6 Destinations

Changes from v5:
  - EmailDeliveryChannel.send() now calls resolve_channel_config() before sending
  - SlackDeliveryChannel.send() now calls resolve_channel_config()
  - TeamsDeliveryChannel.send() now calls resolve_channel_config()
  - All channels are backwards compatible: raw webhook_url still works

Backwards compatibility:
  If channel config contains destination_id  → resolved via destination_resolver
  If channel config contains raw webhook_url → passed through unchanged
  This means no existing skill configs break.
"""

from __future__ import annotations

import json
import logging
import ssl
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from urllib import request as urllib_request
from urllib.error import URLError

import certifi

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


@dataclass
class DeliveryPayload:
    """Normalised alert payload passed to every channel."""
    subject: str
    summary: str
    detail_html: str
    detail_text: str
    query_name: str
    workspace_id: int
    query_id: int
    conditions_failed: list[dict]
    severity: str = "warning"


class BaseDeliveryChannel(ABC):
    channel_type: str

    @abstractmethod
    def send(self, payload: DeliveryPayload, config: dict[str, Any]) -> tuple[bool, str]:
        """Send the alert. Returns (success, message). Must not raise."""


# ---------------------------------------------------------------------------
# Email channel
# ---------------------------------------------------------------------------


class EmailDeliveryChannel(BaseDeliveryChannel):
    channel_type = "email"

    def send(self, payload: DeliveryPayload, config: dict[str, Any]) -> tuple[bool, str]:
        # Resolve destination_id if present (email_group type)
        resolved = _resolve(config, payload.workspace_id)

        recipients = resolved.get("recipients", config.get("recipients", []))
        if not recipients:
            return False, "No recipients configured."

        try:
            from flask import current_app
            from app.email.mailer import get_logo, send_email

            logo_path = get_logo()
            subject = payload.subject
            reply_to = resolved.get("reply_to")

            for recipient in recipients:
                send_email(
                    logo_path=logo_path,
                    subject=subject,
                    to_email=recipient,
                    html=payload.detail_html,
                    reply_to=reply_to,
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
        resolved = _resolve(config, payload.workspace_id)
        webhook_url = resolved.get("webhook_url", "").strip()
        if not webhook_url:
            return False, "No Slack webhook URL configured."

        severity_emoji = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}.get(payload.severity, "⚠️")

        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f"{severity_emoji} {payload.subject}"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": payload.detail_text}},
        ]
        if payload.conditions_failed:
            condition_lines = "\n".join(f"• {c['message']}" for c in payload.conditions_failed)
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Failed conditions:*\n{condition_lines}"},
            })
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"QueryForge · {payload.query_name}"}],
        })
        return self._post_webhook(webhook_url, {"blocks": blocks})

    def _post_webhook(self, url: str, body: dict) -> tuple[bool, str]:
        try:
            data = json.dumps(body).encode("utf-8")
            req = urllib_request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
            with urllib_request.urlopen(req, timeout=10, context=_ssl_context()) as resp:
                response_text = resp.read().decode()
                if resp.status == 200 and response_text == "ok":
                    return True, "Slack alert delivered."
                return False, f"Slack responded: {resp.status} {response_text}"
        except URLError as exc:
            return False, f"Slack webhook error: {exc}"
        except Exception as exc:
            logger.exception("Slack delivery error")
            return False, str(exc)


# ---------------------------------------------------------------------------
# Microsoft Teams channel
# ---------------------------------------------------------------------------


class TeamsDeliveryChannel(BaseDeliveryChannel):
    channel_type = "teams"

    def send(self, payload: DeliveryPayload, config: dict[str, Any]) -> tuple[bool, str]:
        resolved = _resolve(config, payload.workspace_id)
        webhook_url = resolved.get("webhook_url", "").strip()
        if not webhook_url:
            return False, "No Teams webhook URL configured."

        severity_color = {"info": "0078D4", "warning": "F7630C", "critical": "D13438"}.get(payload.severity, "F7630C")

        card = {
            "type": "message",
            "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {"type": "TextBlock", "text": payload.subject, "weight": "Bolder", "size": "Medium",
                         "color": "Warning" if payload.severity == "warning" else "Attention"},
                        {"type": "TextBlock", "text": payload.detail_text, "wrap": True},
                        *self._condition_facts(payload.conditions_failed),
                        {"type": "TextBlock", "text": f"Query: {payload.query_name}", "size": "Small", "isSubtle": True},
                    ],
                    "msteams": {"width": "Full"},
                },
            }],
        }
        return self._post_webhook(webhook_url, card)

    def _condition_facts(self, conditions: list[dict]) -> list[dict]:
        if not conditions:
            return []
        return [{"type": "FactSet", "facts": [
            {"title": f"Condition {i+1}", "value": c["message"]} for i, c in enumerate(conditions)
        ]}]

    def _post_webhook(self, url: str, body: dict) -> tuple[bool, str]:
        try:
            data = json.dumps(body).encode("utf-8")
            req = urllib_request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
            with urllib_request.urlopen(req, timeout=10, context=_ssl_context()) as resp:
                if resp.status in (200, 202):
                    return True, "Teams alert delivered."
                return False, f"Teams responded: {resp.status} {resp.read().decode()}"
        except URLError as exc:
            return False, f"Teams webhook error: {exc}"
        except Exception as exc:
            logger.exception("Teams delivery error")
            return False, str(exc)


# ---------------------------------------------------------------------------
# Channel registry
# ---------------------------------------------------------------------------

CHANNEL_REGISTRY: dict[str, type[BaseDeliveryChannel]] = {
    "email": EmailDeliveryChannel,
    "slack": SlackDeliveryChannel,
    "teams": TeamsDeliveryChannel,
    "webhook": None,  # populated after GenericWebhookDeliveryChannel definition
}


def get_channel(channel_type: str) -> BaseDeliveryChannel:
    if channel_type not in CHANNEL_REGISTRY:
        raise ValueError(f"Unknown delivery channel: {channel_type!r}. Available: {list(CHANNEL_REGISTRY)}")
    return CHANNEL_REGISTRY[channel_type]()


class GenericWebhookDeliveryChannel(BaseDeliveryChannel):
    channel_type = "webhook"

    def send(self, payload: DeliveryPayload, config: dict[str, Any]) -> tuple[bool, str]:
        resolved = _resolve(config, payload.workspace_id)
        url = str(resolved.get("url") or resolved.get("webhook_url") or "").strip()
        if not url:
            return False, "No webhook URL configured."

        method = str(resolved.get("method") or "POST").strip().upper() or "POST"
        if method not in {"POST", "PUT"}:
            return False, f"Unsupported webhook method: {method}"

        headers = {"Content-Type": "application/json"}
        extra_headers = resolved.get("headers")
        if isinstance(extra_headers, dict):
            headers.update({str(k): str(v) for k, v in extra_headers.items()})
        auth_token = str(resolved.get("auth_token") or "").strip()
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        body = {
            "subject": payload.subject,
            "summary": payload.summary,
            "detail_text": payload.detail_text,
            "detail_html": payload.detail_html,
            "query_name": payload.query_name,
            "workspace_id": payload.workspace_id,
            "query_id": payload.query_id,
            "conditions_failed": payload.conditions_failed,
            "severity": payload.severity,
        }
        try:
            data = json.dumps(body).encode("utf-8")
            req = urllib_request.Request(url, data=data, headers=headers, method=method)
            with urllib_request.urlopen(req, timeout=10, context=_ssl_context()) as resp:
                response_text = resp.read().decode()
                if 200 <= resp.status < 300:
                    return True, "Webhook delivered."
                return False, f"Webhook responded: {resp.status} {response_text}"
        except URLError as exc:
            return False, f"Webhook error: {exc}"
        except Exception as exc:
            logger.exception("Generic webhook delivery error")
            return False, str(exc)


CHANNEL_REGISTRY["webhook"] = GenericWebhookDeliveryChannel


# ---------------------------------------------------------------------------
# Internal resolver helper
# ---------------------------------------------------------------------------


def _resolve(config: dict, workspace_id: int) -> dict:
    """
    Resolve destination_id → decrypted config if present.
    Otherwise return config unchanged (backwards compat).
    workspace_id is pulled from config if not passed explicitly.
    """
    ws_id = config.get("workspace_id") or workspace_id
    if "destination_id" in config and ws_id:
        try:
            from app.skills.destination_resolver import resolve_channel_config
            return resolve_channel_config(config, ws_id)
        except Exception as exc:
            logger.error("Failed to resolve destination_id=%s: %s", config.get("destination_id"), exc)
            raise
    return config


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())
