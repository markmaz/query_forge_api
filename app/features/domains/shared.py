from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Tuple

from flask import request

from app.decorators.rbac import require_access, require_admin
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import require_user_id
from app.services.domain.builder_column_feed_service import BuilderColumnFeedService, BuilderFeedQuery
from app.services.domain.domain_admin_write_service import DomainAdminWriteService
from app.services.domain.domain_column_sample_read_service import DomainColumnSampleReadService
from app.services.domain.domain_join_service import DomainJoinService
from app.services.domain.domain_profile_metric_config_service import DomainProfileMetricConfigService
from app.services.domain.domain_recommendation_service import DomainRecommendationService
from app.services.domain.domain_summary_read_service import DomainSummaryReadService
from app.services.domain.domain_table_read_service import DomainTableReadService
from app.services.domain.domain_table_write_service import DomainTableWriteService
from app.services.domain.domain_time_policy_service import DomainTimePolicyService
from app.services.domain.domain_user_read_service import UserDomainReadService
from app.services.domain.domain_user_write_service import DomainUserWriteService
from app.services.domain.planner_domain_capability_service import PlannerDomainCapabilityService
from app.services.domain.planner_rerank_policy_candidate_service import PlannerRerankPolicyCandidateService
from app.services.domain.planner_rerank_policy_candidate_suggestion_service import (
    PlannerRerankPolicyCandidateSuggestionService,
)
from app.services.domain.planner_rerank_policy_service import PlannerRerankPolicyService
from app.services.domains.capabilities_service import DomainCapabilitiesService

logger = logging.getLogger(__name__)

__all__ = [
    "request",
    "token_required",
    "require_access",
    "require_admin",
    "ForgeError",
    "require_user_id",
    "BuilderColumnFeedService",
    "BuilderFeedQuery",
    "DomainAdminWriteService",
    "DomainColumnSampleReadService",
    "DomainJoinService",
    "DomainProfileMetricConfigService",
    "DomainRecommendationService",
    "DomainSummaryReadService",
    "DomainTableReadService",
    "DomainTableWriteService",
    "DomainTimePolicyService",
    "UserDomainReadService",
    "DomainUserWriteService",
    "PlannerDomainCapabilityService",
    "PlannerRerankPolicyCandidateService",
    "PlannerRerankPolicyCandidateSuggestionService",
    "PlannerRerankPolicyService",
    "DomainCapabilitiesService",
    "workspace_id",
    "json_body_dict",
    "int_arg",
    "bool_arg",
    "handle_service_error",
    "run",
]


def workspace_id() -> str:
    value = (request.headers.get("X-Workspace-Id") or "").strip()
    if not value:
        raise ForgeError("Missing X-Workspace-Id header", status_code=400)
    return value


def json_body_dict() -> Dict[str, Any]:
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise ForgeError("Invalid JSON body", status_code=400)
    return body


def int_arg(name: str, default: int) -> int:
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return int(default)
    try:
        return int(raw)
    except ValueError as exc:
        raise ForgeError(f"Invalid integer for '{name}'", status_code=400) from exc


def bool_arg(name: str, default: Optional[bool] = None) -> Optional[bool]:
    raw = (request.args.get(name) or "").strip().lower()
    if raw == "":
        return default
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    raise ForgeError(f"Invalid boolean for '{name}'", status_code=400)


def handle_service_error(error: ForgeError):
    return {"error": str(error)}, getattr(error, "status_code", 400) or 400


def run(handler: Callable[[], Tuple[Any, int]], *, log_message: str, client_error: str):
    return handler()
