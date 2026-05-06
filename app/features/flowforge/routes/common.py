from __future__ import annotations

from typing import Any

from flask import g, request
from flask_restx import Namespace

from app.exceptions.forge_error import ForgeError
from app.features.flowforge.schemas import register_models
from app.features.flowforge.service import FlowForgeService

flowforge_ns = Namespace(
    "flowforge",
    description=(
        "FlowForge workflow studio endpoints. These routes expose the initial "
        "workspace-gated workflow definition catalog, graph validation, and run-inspector placeholder."
    ),
)
models = register_models(flowforge_ns)


def _workspace_id() -> str:
    workspace_id = str(getattr(g, "workspace_id", "") or "").strip()
    if not workspace_id:
        raise ForgeError("Missing X-Workspace-Id header", status_code=400)
    return workspace_id


def _service() -> FlowForgeService:
    import sys

    package = sys.modules.get("app.features.flowforge.routes")
    override = getattr(package, "_service", None) if package is not None else None
    if override is not None and override is not _service:
        return override()
    return FlowForgeService()


def _actor_user_id() -> str:
    return str(getattr(g, "user_id", "") or getattr(g, "current_user_id", "") or "").strip()


def _int_query_arg(name: str, default: int) -> int:
    try:
        return int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default


def _webhook_token() -> str:
    return str(
        request.headers.get("X-FlowForge-Webhook-Token")
        or request.headers.get("X-Jotform-Webhook-Token")
        or request.args.get("token")
        or ""
    ).strip()


def _webhook_payload() -> dict[str, Any]:
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        if isinstance(payload, dict):
            return payload
        return {"payload": payload}
    return request.form.to_dict(flat=True)
