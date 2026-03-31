from __future__ import annotations

from app.services.semantic.plan_service import PlanService
from app.services.semantic.semantic_concept_service import SemanticConceptService
from app.services.semantic.semantic_mapping_service import SemanticMappingService
from app.services.semantic.semantic_registry_service import SemanticRegistryService
from app.services.semantic.semantic_relationship_service import SemanticRelationshipService
from app.services.semantic.semantic_suggestion_service import SemanticSuggestionService


class SemanticFeatureService:
    @staticmethod
    def build_plan_service(plan_service_factory=PlanService) -> PlanService:
        return plan_service_factory()

    @staticmethod
    def build_registry_service(registry_service_factory=SemanticRegistryService) -> SemanticRegistryService:
        return registry_service_factory()

    @staticmethod
    def build_concept_service(concept_service_factory=SemanticConceptService) -> SemanticConceptService:
        return concept_service_factory()

    @staticmethod
    def build_relationship_service(
        relationship_service_factory=SemanticRelationshipService,
    ) -> SemanticRelationshipService:
        return relationship_service_factory()

    @staticmethod
    def build_mapping_service(mapping_service_factory=SemanticMappingService) -> SemanticMappingService:
        return mapping_service_factory()

    @staticmethod
    def build_suggestion_service(
        suggestion_service_factory=SemanticSuggestionService,
    ) -> SemanticSuggestionService:
        return suggestion_service_factory()


semantic_feature_service = SemanticFeatureService()
