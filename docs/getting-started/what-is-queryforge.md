# What is QueryForge?

## What it is

QueryForge is a semantic data governance and query planning platform. It allows users to explore, query, and govern structured data through a natural-language-aware planner backed by a configurable semantic layer. It is deployed as a full-stack web application with a Python Flask backend and a React TypeScript frontend.

## Why it matters

Data teams often struggle to build consistent, governed queries across large, multi-table databases. QueryForge addresses this by introducing a semantic layer (concepts, aliases, mappings, domains) that maps business vocabulary to physical schema, then uses an AI planner to translate user intent into executable SQL. This means analysts can build queries without knowing underlying schema details, and administrators can enforce consistent logic across the organization.

## Who uses it

- **Analysts / end users** — build and run queries through the Query Studio, use ForgeMatch to map external data, and receive AI-generated summaries via Skills.
- **Domain administrators** — configure domains, joins, capabilities, and rerank policies.
- **Semantic administrators** — manage concepts, aliases, relationships, and mappings in the semantic registry.
- **System administrators** — manage workspaces, organizations, datasources, LLM configurations, ingestion jobs, and RBAC roles.

## Key concepts

- **Workspace** — the primary organizational unit. All data, users, and features are scoped to a workspace.
- **Domain** — a curated view of one or more workspace tables, with defined joins, time policies, and capabilities.
- **Semantic layer** — a registry of canonical concepts, aliases, value aliases, and column mappings that translate business terms to physical columns.
- **Planner** — the AI pipeline that takes a natural language prompt plus a domain and produces a structured query plan (SQL JSON).
- **Skills** — automation blocks (threshold alert, AI summary digest, data freshness check, email delivery, webhook delivery) that run against saved queries on a schedule or on demand.
- **ForgeMatch** — an assisted field-mapping tool that uses vector search and LLM ranking to map source file columns to QueryForge workspace columns.
- **ForgeInsights** — a conversational AI interface (projects + threads) for exploring data and insights through an LLM chat.
- **Query Studio** — the interactive query builder and runner where users build, save, and execute queries.
- **RBAC** — workspace-scoped role-based access control. Feature access is gated by both feature entitlements (workspace-level) and user roles (user+workspace-level).

## Related features

- [Domains](../concepts/domains.md)
- [Semantic Registry](../concepts/semantic-registry.md)
- [Planner](../concepts/planner.md)
- [Skills](../concepts/skills.md)
- [ForgeMatch](../concepts/forgematch.md)
- [Workspaces and Organizations](../concepts/workspaces-and-organizations.md)

## Source grounding
- STATUS: CODE_CONFIRMED
- Sources:
  - `app/routes/` (all namespace declarations)
  - `app/skills/registry.py`, `app/skills/base.py`
  - `app/services/planner_domain/service.py`
  - `app/services/query_forge_service.py`
  - `specs/queryforge_rbac_spec.md`
  - `specs/queryforge_agent_layer_codex_spec.md`
