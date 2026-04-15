# Reference: Route Groups

## Purpose

Complete reference of all API route groups, their access requirements, and key endpoints.

## All `/api/v1/` route groups

All endpoints require `Authorization: Bearer <token>` unless marked `PUBLIC`. All workspace-scoped endpoints require `X-Workspace-Id` header.

---

### admin
`@require_role("system:admin")` on all non-health routes. Health routes are public.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/healthz` | Liveness check (PUBLIC) |
| GET | `/admin/health/detailed` | Detailed health |
| GET | `/admin/health/broker` | Celery broker health |
| GET/PUT | `/admin/planner-projection-policies` | Planner projection policies |
| DELETE | `/admin/planner-projection-policies/{id}` | Delete policy |
| GET/POST | `/admin/pipeline-profiles` | Pipeline trace profiles |
| GET | `/admin/pipeline-profiles/{trace_id}` | Single trace |
| GET | `/admin/prompt-feedback` | Prompt feedback list |
| DELETE | `/admin/prompt-feedback/{id}` | Delete feedback |
| POST | `/admin/vector/semantic-concepts/rebuild` | Rebuild concept vectors |
| POST | `/admin/vector/domains/reindex` | Reindex domain vectors |
| POST | `/admin/vector/embeddings/rebuild` | Rebuild embeddings |
| POST | `/admin/vector/rebuild-all` | Rebuild all vectors |
| GET/PUT/DELETE | `/admin/domain-profiles/{domain_id}` | Domain profiles |
| POST | `/admin/domain-profiles/{domain_id}/generate` | Generate single |
| POST | `/admin/domain-profiles/generate` | Generate batch |
| POST | `/admin/domain-profiles/generate-all` | Generate all |
| POST | `/admin/semantic-catalog/build` | Build semantic catalog |
| POST | `/admin/tenancy/bootstrap` | Bootstrap tenant |
| GET/POST | `/admin/organizations` | Organizations |
| GET/PATCH/DELETE | `/admin/organizations/{id}` | Organization detail |
| GET/POST | `/admin/organizations/{id}/memberships` | Org memberships |
| GET/PATCH/DELETE | `/admin/organizations/{id}/memberships/{mid}` | Membership detail |
| GET/POST | `/admin/organizations/{id}/datasources` | Org datasources |
| GET/PATCH/DELETE | `/admin/datasources/{id}` | Datasource detail |
| POST | `/admin/datasources/{id}/test` | Test connection |
| GET | `/admin/datasources/{id}/namespaces` | List namespaces |
| GET/POST | `/admin/workspaces` | Workspace bindings |
| GET/PATCH | `/admin/workspaces/{id}/binding` | Workspace binding |
| GET/PATCH/DELETE | `/admin/workspaces/{id}` | Workspace detail |
| GET/POST | `/admin/workspaces/{id}/memberships` | Workspace members |
| GET/DELETE | `/admin/workspaces/{id}/memberships/{mid}` | Membership detail |

---

### ai
`@require_access("ai")`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/ai/suggest` | AI column/concept suggestion |
| POST | `/ai/suggest-semantic-adapter` | AI suggest with semantic adapter |
| GET | `/ai/health` | AI health (PUBLIC) |

---

### chat
`@require_access("ai")` on minimal chat; `@require_access("forge_insights")` on ForgeInsights chat.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/chat/...` | Minimal chat (NEEDS_VERIFICATION: exact path) |
| POST | `/chat/forge-insights` | ForgeInsights chat |
| GET | `/chat/forge-insights/conversations` | Conversation list |
| GET | `/chat/forge-insights/conversations/{id}` | Conversation detail |
| DELETE | `/chat/forge-insights/conversations/{id}` | Delete conversation |

---

### data-environment
`@require_role("system:admin")`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/data-environment/llm/start` | Start LLM process |
| POST | `/data-environment/llm/stop` | Stop LLM process |
| GET | `/data-environment/llm/status` | LLM process status |

---

### datasources
`@require_role("system:admin")`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/datasources/` | List datasources |

---

### destinations
`@require_access("skills")`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/destinations/types` | List destination types |
| GET/POST | `/destinations/` | List/create destinations |
| GET/PUT/DELETE | `/destinations/{id}` | Destination detail |
| POST | `/destinations/{id}/test` | Test destination |

---

### dictionary
`@require_access("catalog")` for reads; `@require_access("catalog", role="admin")` for writes.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/dictionary/tables` | List tables |
| PATCH | `/dictionary/tables/{id}` | Patch table |
| GET | `/dictionary/columns` | List columns |
| GET | `/dictionary/columns/search` | Search columns |
| PATCH | `/dictionary/columns/{id}` | Patch column |
| POST | `/dictionary/columns/import` | Import columns (CSV/Excel) |

---

### domains
`@require_access("catalog")` for reads; `@require_access("catalog", role="admin")` for writes.

| Method | Path | Description |
|--------|------|-------------|
| GET/POST | `/domains/` | List/create domains |
| POST | `/domains/recommendations/generate` | AI recommendations |
| POST | `/domains/recommendations/apply` | Apply recommendations |
| GET/PATCH/DELETE | `/domains/{id}` | Domain detail |
| GET | `/domains/column-sample` | Column samples |
| GET | `/domains/workspace-tables` | Workspace table list |
| GET/POST | `/domains/{id}/tables` | Domain tables |
| PATCH | `/domains/{id}/tables/{wt_id}/primary` | Set primary table |
| GET/POST | `/domains/{id}/joins` | Domain joins |
| GET/PATCH/DELETE | `/domains/{id}/joins/{join_id}` | Join detail |
| GET/POST | `/domains/{id}/users` | Domain users |
| DELETE | `/domains/{id}/users/{user_id}` | Remove user |
| GET | `/domains/summary` | Domain summaries |
| GET | `/domains/{id}/capabilities` | Domain capabilities |
| GET | `/domains/{id}/overlay-metrics` | Overlay metrics |
| GET/PUT | `/domains/{id}/profile-metrics` | Profile metrics |
| GET/PUT | `/domains/{id}/time-policy` | Time policy |

---

### embeddings
`@require_access("vector")` for search; `@require_access("vector", role="admin")` for rebuilds.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/embeddings/rebuild` | Rebuild embeddings |
| POST | `/embeddings/domains/upsert` | Upsert domain embedding |
| POST | `/embeddings/columns/upsert` | Upsert column embedding |
| POST | `/embeddings/search` | Search embeddings |

---

### executions
`@require_access("exports")`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/executions/start` | Start async execution |
| GET | `/executions/{job_id}/status` | Poll status |
| POST | `/executions/{job_id}/cancel` | Cancel |
| GET | `/executions/{job_id}/results` | Fetch results |

---

### exports
`@require_access("exports")`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/exports/excel` | Create Excel export |
| GET | `/exports/excel/{token}` | Download export |

---

### forge-insights
`@require_access("forge_insights")`

| Method | Path | Description |
|--------|------|-------------|
| GET/POST | `/forge-insights/projects` | Projects list/create |
| GET/PATCH/DELETE | `/forge-insights/projects/{id}` | Project detail |
| GET/POST | `/forge-insights/threads` | Threads list/create |
| GET/PATCH/DELETE | `/forge-insights/threads/{id}` | Thread detail |

---

### forge-match
`@require_access("forge_match")`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/forge-match` | List sessions |
| POST | `/forge-match/upload` | Upload file |
| POST | `/forge-match/{id}/analyze` | Sync analyze |
| POST | `/forge-match/{id}/analyze/start` | Async analyze |
| GET | `/forge-match/status/{job_id}` | Poll analyze job |
| POST | `/forge-match/cancel/{job_id}` | Cancel job |
| GET | `/forge-match/history` | Analyze history |
| GET/DELETE | `/forge-match/{id}` | Session detail/delete |
| PATCH | `/forge-match/{id}/mappings` | Update mappings |
| GET | `/forge-match/{id}/export` | Export mappings |
| POST | `/forge-match/{id}/create-view-draft` | Create view draft |
| POST | `/forge-match/{id}/execute-view-draft-sql` | Execute view draft SQL |
| POST | `/forge-match/{id}/create-domain-draft` | Create domain draft |

---

### ingestion
`@require_access("ingestion", role="admin")`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/ingestion/sync` | Start ingestion |
| GET | `/ingestion/status/{job_id}` | Job status |
| GET | `/ingestion/diagnostics/{job_id}` | Job diagnostics |
| POST | `/ingestion/cancel/{job_id}` | Cancel job |
| GET | `/ingestion/history` | Ingestion history |
| GET | `/ingestion/schemas` | List available schemas |

---

### nlp / nlp-tier2 / nlp-review
`@require_access("ai")`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/nlp/extract` | NLP entity extraction |
| POST | `/nlp/extract-and-search` | Extraction + search |
| POST | `/nlp-tier2/tier2/parse` | Tier2 NER parse |
| GET/POST | `/nlp-review/...` | NLP review queue (admin writes) |

---

### prompt-feedback
`@require_access("ai")`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/prompt-feedback` | Submit prompt feedback |

---

### query_analysis
`@require_access("query_studio")`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/query_analysis/{query_id}/analyze` | Analyze saved query |
| POST | `/query_analysis/analyze` | Inline analyze |

---

### semantic-concepts / aliases / value-aliases / column-maps
`@require_access("semantic")` for reads; `@require_access("semantic", role="admin")` for writes.

---

### semantic-registry / semantic-mappings / semantic-relationships / semantic-suggestions
`@require_access("semantic")` / `@require_access("semantic", role="admin")` as appropriate.

---

### skills
`@require_access("skills")` + ownership checks for user-owned skills.

---

### vector
`@require_access("vector")`

| Method | Path | Description |
|--------|------|-------------|
| POST | `/vector/domains/search` | Domain vector search |

---

### version
PUBLIC

| Method | Path | Description |
|--------|------|-------------|
| GET | `/version` | Application version info |

---

### Workspace LLM
`@require_admin()`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/llm-roles` | List LLM roles |
| GET | `/llm-providers` | List LLM providers |
| GET/POST | `/workspaces/{id}/llms` | List/create workspace LLMs |
| GET/PUT/DELETE | `/workspaces/{id}/llms/{llm_id}` | LLM detail |
| POST | `/workspaces/{id}/llms/{llm_id}/test` | Test LLM connection |

---

## Source grounding
- STATUS: CODE_CONFIRMED
- Sources:
  - All files in `app/routes/`
  - `.claude/audits/backend-audit.md` (complete RBAC audit)
  - `.claude/audits/implementation-notes.md`
