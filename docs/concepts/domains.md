# Domains

## What it is

A domain is a curated, multi-table view that the planner uses as the unit of query planning. It defines which physical tables participate, how they join, what time dimension to use for date filtering, what analytical capabilities are available, and how the planner should rank and select candidates.

## Why it matters

Without domains, the planner would need to reason over raw schema. Domains let administrators encode business knowledge — which tables belong together, what joins are valid, what time columns mean — so that the planner can produce consistent, correct queries without exposing schema complexity to end users.

## Who uses it

- **Domain administrators / semantic admins** — create and configure domains via the Domain Studio or direct API calls.
- **End users** — select domains when building queries in Query Studio.
- **The planner** — selects the best matching domain for a user prompt using vector search and rerank policies.

## Key concepts

- **Primary table** — the central table of a domain. Set via `PATCH /api/v1/domains/{domain_id}/tables/{workspace_table_id}/primary`.
- **Domain tables** — all tables participating in the domain. `GET /api/v1/domains/{domain_id}/tables` returns the list; `POST` adds a table.
- **Joins** — join conditions between domain tables. `GET/POST /api/v1/domains/{domain_id}/joins`, `PATCH/DELETE /api/v1/domains/{domain_id}/joins/{join_id}`.
- **Capabilities** — what analytical operations are enabled for this domain (e.g., which metrics can be computed). `GET /api/v1/domains/{domain_id}/capabilities`.
- **Time policy** — which column to use for date range filtering. `GET/PUT /api/v1/domains/{domain_id}/time-policy`.
- **Profile metrics** — summary statistics or metric definitions overlaid on the domain. `GET/PUT /api/v1/domains/{domain_id}/profile-metrics`.
- **Overlay metrics** — additional metric overlays. `GET /api/v1/domains/{domain_id}/overlay-metrics`.
- **Rerank policies** — policies that control how the planner ranks domain candidates for a given prompt. `GET /api/v1/domains/planner-rerank-policies` (INFERRED_FROM_STRUCTURE from domain_routes.py line 680+).
- **Domain users** — access control: which users can use a domain. `GET/POST /api/v1/domains/{domain_id}/users`, `DELETE /api/v1/domains/{domain_id}/users/{user_id}`.
- **Domain profile embeddings** — vector embeddings of domain profiles, used by the planner for semantic retrieval. Generated via `POST /api/v1/domain-profile-embeddings/{domain_id}/generate`.
- **Domain summary** — a summary representation for planner selection. `GET /api/v1/domains/summary`.

## Related features

- [Semantic Registry](semantic-registry.md)
- [Planner](planner.md)
- [Architecture: Semantic Layer](../architecture/semantic-layer.md)
- [User Guide: Domains Overview](../user-guides/domains-overview.md)
- [Task Playbook: Create a Domain](../task-playbooks/create-a-domain.md)

## Source grounding
- STATUS: CODE_CONFIRMED
- Sources:
  - `app/routes/domain_routes.py` (all route classes and decorators)
  - `app/routes/domain_profile_embeddings.py`
  - `app/routes/vector_domains.py`
  - `src/features/domain-studio/ui/` (directory listing)
