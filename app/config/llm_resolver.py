from __future__ import annotations

import logging
from typing import Any, Dict, Optional

# Conditional import: do not rebind WorkspaceLLMService if it has already been
# set in this module's namespace (e.g. by unittest.mock.patch during a reload).
if "WorkspaceLLMService" not in globals():
    from app.services.tenancy.workspace_llm_service import WorkspaceLLMService

logger = logging.getLogger(__name__)


def resolve_llm_config(workspace_id: str, role: str) -> Optional[Dict[str, Any]]:
    """
    Returns merged LLM config for use in the pipeline.
    DB config takes precedence over env var config (via WorkspaceLLMService).

    The returned dict may contain a decrypted api_key for internal backend use.
    NEVER return this dict via REST or write api_key to logs.
    """
    try:
        return WorkspaceLLMService().get_llm_for_role(workspace_id, role)
    except Exception:
        logger.exception("resolve_llm_config failed ws=%s role=%s", workspace_id, role)
        return None
