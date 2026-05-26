from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Dict, Optional

from app.config import (
    SEMANTIC_LLM_TIMEOUT_SECONDS,
    SEMANTIC_PLAN_LLM_TIMEOUT_SECONDS,
)
from app.constants.llm_roles import LLMRole
from app.constants.llm_roles import LLMProvider
from app.exceptions.forge_error import ForgeError
from app.services.llm.llm_client import LLMClient
from app.services.tenancy.workspace_llm_service import WorkspaceLLMService

logger = logging.getLogger(__name__)

LLM_CONFIG_FALLBACK_ERRORS = (OSError, RuntimeError, TypeError, ValueError)


@dataclass(frozen=True)
class ResolvedLLMRuntime:
    client: LLMClient
    source: str
    role: str
    workspace_id: Optional[str]
    llm_id: Optional[int]
    provider: str
    model: str
    endpoint: str


def resolve_llm_config(
    workspace_id: str,
    role: str,
    *,
    llm_id_override: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Returns DB-backed LLM config for use in the pipeline.
    Resolution order:
      1) explicit llm_id_override
      2) active workspace LLM for the requested role
      3) active workspace LLM for any role (deterministic fallback)

    The returned dict may contain a decrypted api_key for internal backend use.
    NEVER return this dict via REST or write api_key to logs.
    """
    ws = str(workspace_id or "").strip()
    role_norm = str(role or "").strip().lower()
    if role_norm == "":
        return None
    svc = WorkspaceLLMService()
    try:
        if llm_id_override is not None:
            llm_id = int(llm_id_override)
            if llm_id <= 0:
                raise ForgeError("llm_id must be > 0", status_code=400)
            row = svc.get_internal_by_id(llm_id)
            if row is None:
                raise ForgeError("Workspace LLM not found", status_code=404, details={"llm_id": llm_id})
            row_ws = str(row.get("workspace_id") or "").strip()
            if ws and row_ws and row_ws != ws:
                raise ForgeError(
                    "Workspace LLM does not belong to workspace",
                    status_code=403,
                    details={"llm_id": llm_id, "workspace_id": ws},
                )
            if not bool(row.get("is_active")):
                raise ForgeError(
                    "Workspace LLM is inactive",
                    status_code=400,
                    details={"llm_id": llm_id},
                )
            row_role = str(row.get("role") or "").strip().lower()
            if row_role and row_role != role_norm:
                raise ForgeError(
                    "Workspace LLM role mismatch",
                    status_code=400,
                    details={"llm_id": llm_id, "expected_role": role_norm, "actual_role": row_role},
                )
            out = dict(row)
            out["_source"] = "override"
            out["_llm_id"] = llm_id
            return out

        cfg = svc.get_llm_for_role(ws, role_norm)
        if cfg:
            out = dict(cfg)
            if "_source" not in out:
                out["_source"] = "workspace_role"
            return out
        return None
    except ForgeError:
        raise
    except LLM_CONFIG_FALLBACK_ERRORS:
        logger.exception(
            "resolve_llm_config failed ws=%s role=%s llm_id_override=%s",
            ws,
            role_norm,
            llm_id_override,
        )
        return None


def build_llm_client_for_role(
    *,
    workspace_id: str,
    role: str,
    llm_id_override: Optional[int] = None,
    timeout_seconds: Optional[int] = None,
) -> ResolvedLLMRuntime:
    role_norm = str(role or "").strip().lower()
    if role_norm == "":
        raise ForgeError("role is required", status_code=400)

    cfg = resolve_llm_config(
        workspace_id=workspace_id,
        role=role_norm,
        llm_id_override=llm_id_override,
    )
    if cfg is None:
        raise ForgeError(
            "No LLM configuration found for role",
            status_code=404,
            details={
                "workspace_id": str(workspace_id or "").strip(),
                "role": role_norm,
                "hint": "Create at least one active workspace LLM configuration.",
            },
        )

    provider = str(cfg.get("provider") or "generic").strip().lower() or "generic"
    model = str(cfg.get("model_name") or "").strip()
    endpoint = str(cfg.get("endpoint_url") or "").strip()
    api_key = str(cfg.get("api_key") or "").strip() or None
    llm_timeout = int(timeout_seconds or _default_timeout_for_role(role_norm))

    if not model:
        raise ForgeError(
            "LLM model_name is not configured",
            status_code=400,
            details={"workspace_id": str(workspace_id or "").strip(), "role": role_norm},
        )
    if provider == LLMProvider.OPENAI and not endpoint:
        endpoint = "https://api.openai.com/v1"
    if provider in {LLMProvider.GENERIC, LLMProvider.OLLAMA, LLMProvider.AZURE_OPENAI} and not endpoint:
        raise ForgeError(
            "LLM endpoint is not configured",
            status_code=400,
            details={"workspace_id": str(workspace_id or "").strip(), "role": role_norm, "provider": provider},
        )
    if provider in {LLMProvider.OPENAI, LLMProvider.ANTHROPIC, LLMProvider.AZURE_OPENAI} and not api_key:
        raise ForgeError(
            "LLM api_key is not configured",
            status_code=400,
            details={"workspace_id": str(workspace_id or "").strip(), "role": role_norm, "provider": provider},
        )

    unsupported_provider = provider in {"anthropic"}
    if unsupported_provider:
        raise ForgeError(
            "Configured provider is not supported by runtime chat client",
            status_code=400,
            details={
                "provider": provider,
                "role": role_norm,
                "hint": "Use openai/generic/ollama/azure_openai endpoint for runtime planner flows",
            },
        )

    client = LLMClient(
        endpoint=endpoint,
        model=model,
        timeout_seconds=llm_timeout,
        api_key=api_key,
    )
    source = str(cfg.get("_source") or "workspace_role").strip()
    llm_id = _to_int_or_none(cfg.get("_llm_id") or cfg.get("id"))
    return ResolvedLLMRuntime(
        client=client,
        source=source or "workspace_role",
        role=role_norm,
        workspace_id=str(workspace_id or "").strip() or None,
        llm_id=llm_id,
        provider=provider,
        model=model,
        endpoint=endpoint,
    )


def _default_timeout_for_role(role: str) -> int:
    role_norm = str(role or "").strip().lower()
    if role_norm in {LLMRole.PLANNER, LLMRole.QUERY_GENERATOR, LLMRole.ENRICHMENT, LLMRole.FLOWFORGE_RULE_DRAFTING}:
        return int(SEMANTIC_PLAN_LLM_TIMEOUT_SECONDS)
    return int(SEMANTIC_LLM_TIMEOUT_SECONDS)


def _to_int_or_none(value: Any) -> Optional[int]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
