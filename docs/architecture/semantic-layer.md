# Architecture: Semantic Layer

## Purpose

The semantic layer is the bridge between business vocabulary and physical database schema. It stores canonical concepts, aliases, value normalizations, column mappings, and concept relationships. Both the planner and ForgeMatch rely on it to resolve user intent to physical columns.

## Components

| Component | Storage | Description |
|-----------|---------|-------------|
| Semantic concepts | MySQL (`semantic_concept` table) | Canonical business terms |
| Concept aliases | MySQL | Alternate phrasings/names for concepts |
| Value aliases | MySQL | Normalized values for filter terms |
| Concept column maps | MySQL | Maps concept → physical column in domain |
| Semantic relationships | MySQL | Relations between concepts |
| Semantic registry | MySQL | Higher-level registry objects (NEEDS_VERIFICATION: exact distinction from concepts) |
| Semantic mappings | MySQL | Column-level mappings (NEEDS_VERIFICATION: exact distinction from column maps) |
| Concept vector index | Qdrant (`semantic_concepts_v1`) | Embeddings for semantic concept search |

## Flow

### Planner semantic integration

1. Planner receives LLM output (schema v2 plan with raw column/metric names).
2. `SemanticIntegrationService` performs concept key lookup against the semantic registry.
3. Value alias resolution (`ValueAliasResolutionService`) normalizes filter values (e.g., "Q1" → date range).
4. Boolean filter helpers normalize boolean concept aliases.
5. Resolved concept keys and values are written back into the plan.

### Planner domain selection

1. User prompt (normalized) is embedded using the configured embedding model.
2. Qdrant `table_catalog` collection is queried for candidate domain profiles.
3. Candidates are reranked by `PlannerDomainRerankPolicyEngine`.

### Semantic concept retrieval

1. For concept scoring, the planner also queries Qdrant `semantic_concepts_v1`.
2. `SemanticGroundingService` (`app/services/planner/semantic_grounding_service.py`) handles the concept → column resolution path.

### ForgeMatch integration

ForgeMatch uses concept column maps when scoring mapping candidates. If a source field matches a concept alias, the concept's column maps are used to boost candidate confidence.

## Inputs / Outputs

**Semantic concept lookup input:** concept key, domain_id / workspace context
**Semantic concept lookup output:** matched concept + column map details

**Value alias resolution input:** filter value string, concept key
**Value alias resolution output:** normalized value or date range

## Important decisions

- **Qdrant is the search index; MySQL is the source of truth** — all semantic data is persisted in MySQL. Qdrant stores embeddings derived from MySQL records. If they drift, run `POST /api/v1/semantic-concepts/rebuild-index`.
- **Two concept namespaces** — there are both `semantic_concepts` and `semantic_registry` routes. Their exact relationship is NEEDS_VERIFICATION.
- **Suggestion pipeline** — semantic suggestions (`/api/v1/semantic-suggestions/`) provide an AI-assisted workflow for discovering new concepts and mappings from the workspace catalog.

## Related systems

- [Planner Pipeline](planner-pipeline.md)
- [Concepts: Semantic Registry](../concepts/semantic-registry.md)
- [Concepts: Domains](../concepts/domains.md)

## Source grounding
- STATUS: CODE_CONFIRMED
- Sources:
  - `app/routes/semantic_concepts.py`
  - `app/routes/semantic_registry.py`
  - `app/routes/semantic_mappings.py`
  - `app/routes/semantic_relationships.py`
  - `app/services/planner_domain/semantic_integration_service.py` (existence confirmed)
  - `app/services/semantic_registry_service.py`
