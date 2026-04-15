# Semantic Registry

## What it is

The semantic registry is a structured dictionary of canonical business concepts that bridges business vocabulary and physical database schema. It stores concepts, their aliases, value aliases, column mappings, and relationships. Concepts are stored in MySQL and indexed in Qdrant for vector retrieval.

## Why it matters

The planner and ForgeMatch both rely on the semantic registry to resolve user language ("enrollment", "attendance rate", "school year") to actual database columns. Without a populated registry, the planner must rely solely on column name similarity, which degrades query accuracy. A well-maintained registry is the primary lever for improving query quality.

## Who uses it

- **Semantic administrators** — create, update, and maintain concepts via the Semantic Admin UI or direct API.
- **The planner** — performs vector search against the Qdrant `semantic_concepts_v1` collection to find relevant concepts for a given prompt.
- **ForgeMatch** — uses concept column maps to score mapping candidates.

## Key concepts

### Semantic Concept
A canonical business term. Fields include a key (slug), display name, description, and concept type. Managed at `GET/POST /api/v1/semantic-concepts`, `GET/PATCH/DELETE /api/v1/semantic-concepts/{concept_id}`.

### Concept Aliases
Alternate names or phrasings for a concept. When a user types an alias, the planner resolves it to the canonical concept. Managed at `GET/POST /api/v1/semantic-concept-aliases`, `GET/PATCH/DELETE /api/v1/semantic-concept-aliases/{alias_id}`.

### Value Aliases
Normalized values for filter terms. For example, "Q1" → "2024-01-01 to 2024-03-31". Managed at `GET/POST /api/v1/semantic-value-aliases`, `GET/PATCH/DELETE /api/v1/semantic-value-aliases/{value_alias_id}`.

### Concept Column Maps
Maps a semantic concept to a physical column in a specific domain or workspace table. This is how the planner translates "enrollment count" to `fact_enrollment.student_count`. Managed at `GET/POST /api/v1/semantic-concept-column-maps`, `GET/PATCH/DELETE /api/v1/semantic-concept-column-maps/{map_id}`.

### Semantic Relationships
Defines how two concepts relate (e.g., "school" → "district", "student" → "enrollment"). Managed at `GET/POST /api/v1/semantic-relationships`, `GET/PATCH/DELETE /api/v1/semantic-relationships/{relationship_id}`. Concept lookup: `GET /api/v1/semantic-relationships/concepts`.

### Semantic Registry Entries
A higher-level registry object (separate from concepts). `GET/POST /api/v1/semantic-registry`, `GET/PATCH/DELETE /api/v1/semantic-registry/{entry_id}`. NEEDS_VERIFICATION: the distinction between `semantic-registry` and `semantic-concepts` namespaces is not fully clear from code alone.

### Semantic Mappings
Column-level semantic mappings (possibly mapping physical columns to registry entries). `GET/POST /api/v1/semantic-mappings`, `DELETE /api/v1/semantic-mappings/{mapping_id}`.

### Semantic Suggestions
AI-assisted suggestions for concepts or mappings. `POST /api/v1/semantic-suggestions/runs` starts a suggestion run; `POST /api/v1/semantic-suggestions/runs/{run_id}/execute` runs it; `GET /api/v1/semantic-suggestions/items` lists suggestions; `PATCH /api/v1/semantic-suggestions/items/{item_id}` accepts/rejects; `POST /api/v1/semantic-suggestions/runs/{run_id}/apply` applies accepted items.

### Vector Index
Concepts are indexed in Qdrant (`semantic_concepts_v1`). Rebuild via admin routes: `POST /api/v1/admin/vector/semantic-concepts/rebuild` or `POST /api/v1/semantic-concepts/rebuild-index`.

## Related features

- [Domains](domains.md)
- [Planner](planner.md)
- [Architecture: Semantic Layer](../architecture/semantic-layer.md)

## Source grounding
- STATUS: CODE_CONFIRMED
- Sources:
  - `app/routes/semantic_concepts.py`
  - `app/routes/semantic_registry.py`
  - `app/routes/semantic_mappings.py`
  - `app/routes/semantic_relationships.py`
  - `app/routes/semantic_suggestions.py`
  - `app/services/semantic_registry_service.py`
  - `src/features/semantic-admin/ui/` (directory listing)
