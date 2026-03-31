from app.routes.semantic_concepts import (
    semantic_concept_aliases_ns,
    semantic_concept_column_maps_ns,
    semantic_concepts_ns,
    semantic_value_aliases_ns,
)
from app.routes.semantic_mappings import semantic_mappings_ns
from app.routes.semantic_registry import semantic_registry_ns
from app.routes.semantic_relationships import semantic_relationships_ns
from app.routes.semantic_routes import semantic_ns
from app.routes.semantic_suggestions import semantic_suggestions_ns

NAMESPACES = [
    (semantic_concepts_ns, ("semantic", "concepts")),
    (semantic_concept_aliases_ns, ("semantic", "concept-aliases")),
    (semantic_value_aliases_ns, ("semantic", "value-aliases")),
    (semantic_concept_column_maps_ns, ("semantic", "concept-column-maps")),
    (semantic_registry_ns, ("semantic", "registry")),
    (semantic_mappings_ns, ("semantic", "mappings")),
    (semantic_relationships_ns, ("semantic", "relationships")),
    (semantic_suggestions_ns, ("semantic", "suggestions")),
    (semantic_ns, ("semantic",)),
]
