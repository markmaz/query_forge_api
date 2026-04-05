from __future__ import annotations

from app.routes.admin.base import admin_ns
from app.routes.admin.helpers import (
    _as_bool,
    _assert_workspace_admin_datasource_access,
    _assert_workspace_admin_organization_access,
    _current_workspace_binding,
    _is_super_admin_request,
    _matches_scoped_organization_row,
    _matches_scoped_workspace_row,
    _paged_rows,
    _require_admin,
)
from app.services.admin.domain_profile_embedding_service import (
    DomainProfileEmbeddingService,
)
from app.services.admin.domain_profile_service import DomainProfileService
from app.services.admin.health_service import AdminHealthService
from app.services.domain.planner_domain_selection_policy_service import (
    PlannerDomainSelectionPolicyService,
)
from app.services.domain.planner_prompt_intent_policy_service import (
    PlannerPromptIntentPolicyService,
)
from app.services.domain.planner_projection_policy_service import (
    PlannerProjectionPolicyService,
)
from app.services.domain.planner_retrieval_policy_service import (
    PlannerRetrievalPolicyService,
)
from app.services.domain.planner_signal_policy_service import (
    PlannerSignalPolicyService,
)
from app.services.embedding.embedding_index_service import EmbeddingIndexService
from app.services.embedding.semantic_concept_embedding_service import (
    SemanticConceptEmbeddingService,
)
from app.services.prompt_feedback_service import PromptFeedbackService
from app.services.semantic.catalog.semantic_catalog_builder import SemanticCatalogBuilder
from app.services.tenancy.tenancy_admin_service import TenancyAdminService
from app.services.tenancy.tenancy_bootstrap_service import TenancyBootstrapService
from app.services.vector import DomainVectorIndexService

from app.routes.admin import misc_routes as _misc_routes
from app.routes.admin import planner_policy_routes as _planner_policy_routes
from app.routes.admin import tenancy_routes as _tenancy_routes
from app.routes.admin import vector_domain_routes as _vector_domain_routes

_REGISTERED_ROUTE_MODULES = (
    _misc_routes,
    _planner_policy_routes,
    _tenancy_routes,
    _vector_domain_routes,
)

__all__ = [
    "AdminHealthService",
    "DomainProfileEmbeddingService",
    "DomainProfileService",
    "DomainVectorIndexService",
    "EmbeddingIndexService",
    "PlannerDomainSelectionPolicyService",
    "PlannerProjectionPolicyService",
    "PlannerPromptIntentPolicyService",
    "PlannerRetrievalPolicyService",
    "PlannerSignalPolicyService",
    "PromptFeedbackService",
    "SemanticCatalogBuilder",
    "SemanticConceptEmbeddingService",
    "TenancyAdminService",
    "TenancyBootstrapService",
    "_as_bool",
    "_assert_workspace_admin_datasource_access",
    "_assert_workspace_admin_organization_access",
    "_current_workspace_binding",
    "_is_super_admin_request",
    "_matches_scoped_organization_row",
    "_matches_scoped_workspace_row",
    "_paged_rows",
    "_require_admin",
    "admin_ns",
]
