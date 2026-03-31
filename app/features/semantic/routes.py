from .semantic_concepts_api import (
    semantic_concept_aliases_ns,
    semantic_concept_column_maps_ns,
    semantic_concepts_ns,
    semantic_value_aliases_ns,
)
from .semantic_mappings_api import semantic_mappings_ns
from .semantic_plan_api import semantic_ns
from .semantic_registry_api import semantic_registry_ns
from .semantic_relationships_api import semantic_relationships_ns
from .semantic_suggestions_api import semantic_suggestions_ns

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
