from __future__ import annotations

import sys

from app.services.admin.domain_profile_embedding_service import (
    DomainProfileEmbeddingService as _DomainProfileEmbeddingService,
)
from app.services.admin.domain_profile_service import (
    DomainProfileService as _DomainProfileService,
)
from app.services.admin.health_service import AdminHealthService as _AdminHealthService
from app.services.domain.planner_domain_selection_policy_service import (
    PlannerDomainSelectionPolicyService as _PlannerDomainSelectionPolicyService,
)
from app.services.domain.planner_prompt_intent_policy_service import (
    PlannerPromptIntentPolicyService as _PlannerPromptIntentPolicyService,
)
from app.services.domain.planner_projection_policy_service import (
    PlannerProjectionPolicyService as _PlannerProjectionPolicyService,
)
from app.services.domain.planner_retrieval_policy_service import (
    PlannerRetrievalPolicyService as _PlannerRetrievalPolicyService,
)
from app.services.domain.planner_signal_policy_service import (
    PlannerSignalPolicyService as _PlannerSignalPolicyService,
)
from app.services.embedding.embedding_index_service import (
    EmbeddingIndexService as _EmbeddingIndexService,
)
from app.services.embedding.semantic_concept_embedding_service import (
    SemanticConceptEmbeddingService as _SemanticConceptEmbeddingService,
)
from app.services.prompt_feedback_service import (
    PromptFeedbackService as _PromptFeedbackService,
)
from app.services.semantic.catalog.semantic_catalog_builder import (
    SemanticCatalogBuilder as _SemanticCatalogBuilder,
)
from app.services.tenancy.tenancy_admin_service import (
    TenancyAdminService as _TenancyAdminService,
)
from app.services.tenancy.tenancy_bootstrap_service import (
    TenancyBootstrapService as _TenancyBootstrapService,
)
from app.services.vector import DomainVectorIndexService as _DomainVectorIndexService


def _resolve(name: str, default):
    module = sys.modules.get("app.routes.admin_routes")
    if module is None:
        return default
    return getattr(module, name, default)


def admin_health_service():
    return _resolve("AdminHealthService", _AdminHealthService)()


def planner_projection_policy_service():
    return _resolve("PlannerProjectionPolicyService", _PlannerProjectionPolicyService)()


def planner_signal_policy_service():
    return _resolve("PlannerSignalPolicyService", _PlannerSignalPolicyService)()


def planner_prompt_intent_policy_service():
    return _resolve(
        "PlannerPromptIntentPolicyService",
        _PlannerPromptIntentPolicyService,
    )()


def planner_retrieval_policy_service():
    return _resolve("PlannerRetrievalPolicyService", _PlannerRetrievalPolicyService)()


def planner_domain_selection_policy_service():
    return _resolve(
        "PlannerDomainSelectionPolicyService",
        _PlannerDomainSelectionPolicyService,
    )()


def prompt_feedback_service():
    return _resolve("PromptFeedbackService", _PromptFeedbackService)()


def domain_profile_service():
    return _resolve("DomainProfileService", _DomainProfileService)()


def domain_profile_embedding_service():
    return _resolve("DomainProfileEmbeddingService", _DomainProfileEmbeddingService)()


def semantic_catalog_builder():
    return _resolve("SemanticCatalogBuilder", _SemanticCatalogBuilder)()


def semantic_concept_embedding_service():
    return _resolve(
        "SemanticConceptEmbeddingService",
        _SemanticConceptEmbeddingService,
    )()


def embedding_index_service():
    return _resolve("EmbeddingIndexService", _EmbeddingIndexService)()


def domain_vector_index_service():
    return _resolve("DomainVectorIndexService", _DomainVectorIndexService)()


def tenancy_admin_service():
    return _resolve("TenancyAdminService", _TenancyAdminService)()


def tenancy_bootstrap_service():
    return _resolve("TenancyBootstrapService", _TenancyBootstrapService)()
