# Goal: Create a Domain

## Audience

Domain administrators and workspace administrators who need to configure a new domain for Query Studio.

## What you need

- `catalog:admin` role (or `workspace_admin`)
- At least one ingested workspace table (run ingestion first)
- Basic knowledge of the physical schema (which tables and join keys)

## Steps

1. **Verify workspace tables are ingested**
   Go to ingestion or workspace inventory. Run `POST /api/v1/ingestion/sync` if tables are not yet synced. Wait for the job to complete.

2. **Create the domain**
   `POST /api/v1/domains/` with a domain name and optional description. Note the returned `domain_id`.

3. **Add the primary table**
   `POST /api/v1/domains/{domain_id}/tables` with the workspace table ID.
   `PATCH /api/v1/domains/{domain_id}/tables/{workspace_table_id}/primary` to mark it primary.

4. **Add secondary tables (if needed)**
   `POST /api/v1/domains/{domain_id}/tables` for each additional table.

5. **Define joins**
   `POST /api/v1/domains/{domain_id}/joins` for each join between tables. Provide:
   - Source table ID
   - Target table ID
   - Join key columns and conditions

6. **Set the time policy**
   `PUT /api/v1/domains/{domain_id}/time-policy` — specify which column to use for date range filtering.

7. **Configure profile metrics (optional)**
   `PUT /api/v1/domains/{domain_id}/profile-metrics` — define key metrics that the planner should know about.

8. **Generate domain profile embeddings**
   `POST /api/v1/domain-profile-embeddings/{domain_id}/generate` — this creates vector embeddings used by the planner for domain selection. Without this step, the domain will not appear in planner candidate results.

9. **Add semantic concept mappings (optional but recommended)**
   In the Semantic Admin, add concept column maps linking canonical concepts to columns in this domain. This significantly improves planner accuracy.

10. **Test by running a query**
    Go to Query Studio, select the new domain, and run a test query. Verify the planner selects the correct domain and resolves concepts as expected.

## What happens next

The domain is available in Query Studio. Users with appropriate access can run queries against it. Refine capabilities, rerank policies, and semantic mappings over time to improve query quality.

## Common issues

- **Domain not appearing in planner results** — profile embeddings may not have been generated. Run `POST /api/v1/domain-profile-embeddings/{domain_id}/generate`.
- **Planner selecting wrong join** — review join configurations. Check that join keys are correctly specified.
- **Poor concept resolution** — add concept column maps in the Semantic Admin to map business terms to physical columns.

## Related docs

- [Concepts: Domains](../concepts/domains.md)
- [User Guide: Domains Overview](../user-guides/domains-overview.md)
- [Troubleshoot: Wrong Domain Selected](../troubleshooting/wrong-domain-selected.md)

## Source grounding
- STATUS: CODE_CONFIRMED
- Sources:
  - `app/routes/domain_routes.py`
  - `app/routes/domain_profile_embeddings.py`
  - `app/routes/ingestion_routes.py`
