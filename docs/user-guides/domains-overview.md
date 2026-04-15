# Domains User Guide

## What it is

The Domain Studio is the administrative interface for creating and configuring domains. A domain is a curated multi-table view that the planner and Query Studio use as the unit of query planning.

## Who uses it

Domain administrators and workspace administrators with `catalog:admin` role.

## What you can do

### Browse and search domains
View all domains in your workspace. The `GET /api/v1/domains/` endpoint returns the list. The frontend is at `src/features/domain-studio/ui/` (INFERRED_FROM_STRUCTURE).

### Create a domain
`POST /api/v1/domains/` — creates a new domain. Provide a name and optional configuration.

### Add tables to a domain
`POST /api/v1/domains/{domain_id}/tables` — add a workspace table. `GET /api/v1/domains/{domain_id}/tables` — view current tables.

Set the primary table via `PATCH /api/v1/domains/{domain_id}/tables/{workspace_table_id}/primary`.

### Configure joins
`POST /api/v1/domains/{domain_id}/joins` — define a join between two domain tables. `PATCH/DELETE /api/v1/domains/{domain_id}/joins/{join_id}` — update or remove.

### Set the time policy
`PUT /api/v1/domains/{domain_id}/time-policy` — configure which column is used for date filtering.

### Configure capabilities
`GET /api/v1/domains/{domain_id}/capabilities` — view configured capabilities. Capabilities tell the planner which analytical operations (aggregations, breakdowns) are valid for this domain.

### Manage domain users
`GET/POST /api/v1/domains/{domain_id}/users` — grant or list user access to a domain.
`DELETE /api/v1/domains/{domain_id}/users/{user_id}` — remove access.

### Generate domain profile embeddings
`POST /api/v1/domain-profile-embeddings/{domain_id}/generate` — generates vector embeddings for the domain profile used by the planner for semantic domain selection.

### AI-assisted domain recommendations
`POST /api/v1/domains/recommendations/generate` — generate AI-suggested domain configurations.
`POST /api/v1/domains/recommendations/apply` — apply accepted recommendations.

### Column sample exploration
`GET /api/v1/domains/column-sample` — fetch sample values for workspace columns, used during domain configuration.

### Workspace tables
`GET /api/v1/domains/workspace-tables` — browse available workspace tables for adding to a domain.

## Common issues

- Domain not appearing in Query Studio — check that the domain has at least one table, joins are valid, and profile embeddings have been generated.
- Wrong domain selected by planner — see [troubleshooting/wrong-domain-selected.md](../troubleshooting/wrong-domain-selected.md).

## Related docs

- [Concepts: Domains](../concepts/domains.md)
- [Task Playbook: Create a Domain](../task-playbooks/create-a-domain.md)

## Source grounding
- STATUS: CODE_CONFIRMED
- Sources:
  - `app/routes/domain_routes.py`
  - `app/routes/domain_profile_embeddings.py`
  - `src/features/domain-studio/ui/` (directory listing)
