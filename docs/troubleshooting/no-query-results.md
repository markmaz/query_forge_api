# Problem: Query Returns No Results

## Symptoms

- Execution completes successfully but the results table is empty
- Total count shows 0
- No error is shown

## Likely causes

1. **Filters are too restrictive** — date range, entity, or value filters narrow the data to zero rows
2. **Wrong time policy** — the domain's time column doesn't match the data's actual date range
3. **Stale data** — the datasource hasn't been updated recently (check with a data freshness skill)
4. **Wrong join type** — domain joins exclude rows that should be included
5. **Value alias mismatch** — a filter value was normalized to a non-matching form
6. **Domain is empty** — the underlying tables have no data for this workspace/tenant

## How to confirm

1. Remove filters one by one and re-execute to identify which filter causes the zero result.
2. Check the `qf_rendered_sql` in the plan response to see the exact SQL being run.
3. Connect to the datasource directly and run the rendered SQL to confirm the data issue is in the database, not in QueryForge.
4. Check the time policy for the domain: `GET /api/v1/domains/{domain_id}/time-policy` — ensure the date column and filter period are correct.

## How to fix

### Fix 1: Relax the time range
Ask for a broader time range in your prompt (e.g., "this year" instead of "this month").

### Fix 2: Check value aliases
Review value aliases in the Semantic Admin (`GET /api/v1/semantic-value-aliases`). If a filter value was incorrectly normalized, update or remove the alias.

### Fix 3: Review domain time policy
`PUT /api/v1/domains/{domain_id}/time-policy` — verify the date column and ensure it matches where data actually lives in the tables.

### Fix 4: Run ingestion
If the workspace tables may be out of date: `POST /api/v1/ingestion/sync`. Wait for completion.

## Related docs

- [Troubleshoot: Planner Output Playbook](../task-playbooks/troubleshoot-planner-output.md)
- [Troubleshoot: Mapping Ambiguity](mapping-ambiguity.md)

## Source grounding
- STATUS: INFERRED_FROM_STRUCTURE
- Sources:
  - `app/services/query_forge_service.py` (run/compile logic)
  - `app/routes/domain_routes.py` (time-policy route)
