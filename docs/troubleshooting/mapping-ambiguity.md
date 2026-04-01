# Problem: Mapping Ambiguity (Wrong Columns Resolved)

## Symptoms

- The plan selects a column with a similar name to what you intended but from a different table
- Metric results appear to be from the wrong concept (e.g., "count" resolves to a row count instead of an enrollment count)
- The explanation shows multiple concepts matched with similar scores
- ForgeMatch suggestions show low confidence or inconsistent candidates

## Likely causes

1. **Multiple columns with similar names** across tables — planner can't disambiguate without semantic grounding
2. **Missing concept column maps** — planner falls back to column-name similarity which is less precise
3. **Overlapping concept aliases** — two concepts share aliases, causing the wrong one to match
4. **Value alias normalization** — a filter term was normalized in an unexpected way
5. **ForgeMatch: workspace column embeddings out of date** — column embeddings don't reflect current schema

## How to confirm

1. Review the plan explanation — which specific columns were selected?
2. Check which concepts were resolved in the plan (`norm_debug` or explanation field).
3. In Semantic Admin, search for concepts by alias and check if multiple concepts share the same alias.
4. For ForgeMatch: review candidate confidence scores — all below 0.5 suggests poor semantic coverage.

## How to fix

### Fix 1: Add concept column maps
Navigate to Semantic Admin → Concept Column Maps. Add an explicit mapping from the intended concept to the specific column in the target domain. This overrides similarity-based resolution.

### Fix 2: Remove conflicting aliases
If two concepts share an alias that causes ambiguity, remove the alias from the less-relevant concept or make it more specific.

### Fix 3: Add a more specific alias
Add a highly specific alias to the correct concept that distinguishes it from the ambiguous term.

### Fix 4: Rebuild concept vector index
If concept data has been updated but the Qdrant index is stale:
```
POST /api/v1/semantic-concepts/rebuild-index
```
Or via admin: `POST /api/v1/admin/vector/semantic-concepts/rebuild`.

### Fix 5: Rebuild workspace column embeddings (ForgeMatch)
If ForgeMatch quality degraded after schema changes:
```
POST /api/v1/embeddings/rebuild
```

## Related docs

- [Concepts: Semantic Registry](../concepts/semantic-registry.md)
- [Troubleshoot: Wrong Domain Selected](wrong-domain-selected.md)

## Source grounding
- STATUS: INFERRED_FROM_STRUCTURE
- Sources:
  - `app/routes/semantic_concepts.py`
  - `app/routes/embeddings.py`
  - `app/services/planner_domain/semantic_integration_service.py` (existence confirmed)
