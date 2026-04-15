# Problem: Wrong Domain Selected by Planner

## Symptoms

- Query results are from the wrong subject area
- The explanation mentions an unexpected domain name
- Columns or metrics from a different domain appear in the plan

## Likely causes

1. **Domain profile embeddings not generated** for the correct domain — so the domain doesn't score well in vector search
2. **Semantic concepts are missing or poorly aliased** — planner resolves prompt terms to a different domain's concepts
3. **Multiple domains have overlapping column names** — rerank policy does not differentiate well
4. **Prompt is too generic** — "show me counts by school" could match multiple domains
5. **Workspace rerank policy** is misconfigured, giving a different domain higher priority

## How to confirm

1. Check the explanation field in the plan response — it names the selected domain.
2. If pipeline tracing is enabled, retrieve the trace at `GET /api/v1/admin/pipeline-profiles/{trace_id}` and look at domain candidate scores.
3. Check that the correct domain has profile embeddings: `GET /api/v1/admin/domain-profiles/{domain_id}`.

## How to fix

### Fix 1: Regenerate domain profile embeddings
```
POST /api/v1/domain-profile-embeddings/{domain_id}/generate
```
Wait for completion, then retry the query.

### Fix 2: Add semantic concept column maps for the correct domain
In the Semantic Admin, add concept-column mappings that associate your intended concepts with the correct domain's columns. This improves planner ranking accuracy.

### Fix 3: Add a domain-specific alias
If a key term in your prompt is ambiguous, add a concept alias that is only mapped to the correct domain.

### Fix 4: Be more specific in the prompt
Include the domain name or a unique term associated with the correct domain in your prompt.

### Fix 5: Review rerank policies
`GET /api/v1/domains/planner-rerank-policies` — check if workspace-level rerank policies are boosting the wrong domain. Adjust via admin routes.

## Related docs

- [Troubleshoot: Planner Output Playbook](../task-playbooks/troubleshoot-planner-output.md)
- [Concepts: Planner](../concepts/planner.md)
- [Task Playbook: Create a Domain](../task-playbooks/create-a-domain.md)

## Source grounding
- STATUS: CODE_CONFIRMED (routes), INFERRED_FROM_STRUCTURE (diagnostic steps)
- Sources:
  - `app/routes/admin_routes.py` (pipeline-profiles)
  - `app/routes/domain_profile_embeddings.py`
  - `app/services/planner_domain/service.py`
