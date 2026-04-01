# Query Studio User Guide

## What it is

Query Studio is the interactive query builder and runner. Users select a domain, write a natural-language prompt (or build a query manually), execute it, view results, and optionally save the query or export the data.

## Why it matters

Query Studio is the primary interface for most QueryForge users. It abstracts SQL complexity behind a guided workflow while giving power users full access to plan details, filters, and SQL output.

## Who uses it

Users with the `query_studio:user` role in a workspace where the `query_studio` feature is entitled.

## Key concepts

### Domain Selection
Before querying, the user selects a domain. The `GET /api/v1/domains/summary` endpoint returns a list of available domains with metadata for display. Domains also support `GET /api/v1/query-studio/domains` (INFERRED_FROM_STRUCTURE from query_studio_routes.py referenced in RBAC audit) for the Query Studio-specific feed, and `GET /api/v1/query-studio/domains/{domain_id}/explorer` for domain exploration.

### Query Planning
The user submits a natural-language prompt. The frontend calls the planner which returns a structured plan including SQL, explanation, selected columns, filters, groupings, and next action suggestions.

### Execution
Query execution is async via Celery:
- `POST /api/v1/executions/start` — submit the compiled SQL for execution
- `GET /api/v1/executions/{job_id}/status` — poll until complete or failed
- `POST /api/v1/executions/{job_id}/cancel` — cancel an in-flight execution
- `GET /api/v1/executions/{job_id}/results` — fetch results (rows and columns)

### Export
Results can be exported to Excel:
- `POST /api/v1/exports/excel` — generate export, returns a token
- `GET /api/v1/exports/excel/{token}` — download file

### AI Inline Analysis
After running a query, users can request an AI analysis of the results:
- `POST /api/v1/query_analysis/{query_id}/analyze` — runs the saved query, builds a dataset profile, and calls the summarizer LLM
- `POST /api/v1/query_analysis/analyze` — inline version (does not require a saved query)

Analysis returns a narrative summary and highlights. Returns 503 if no LLM is configured for the `summarizer` role.

### Saving Queries
Queries can be saved to the query tree. Saved queries are organized in folders, can be moved, shared, trashed, and restored.

### Prompt Feedback
Users can submit feedback on plan quality via `POST /api/v1/prompt-feedback`. This enables feedback-driven improvement of the planner over time.

## Common issues

- Planner selects wrong domain — see [troubleshooting/wrong-domain-selected.md](../troubleshooting/wrong-domain-selected.md)
- Query returns no results — see [troubleshooting/no-query-results.md](../troubleshooting/no-query-results.md)
- LLM returns an error — see [troubleshooting/llm-failure.md](../troubleshooting/llm-failure.md)
- Plan output looks ambiguous — see [troubleshooting/mapping-ambiguity.md](../troubleshooting/mapping-ambiguity.md)

## Source grounding
- STATUS: CODE_CONFIRMED (routes), NEEDS_VERIFICATION (exact UI interaction patterns)
- Sources:
  - `app/routes/execution_routes.py`
  - `app/routes/export_routes.py`
  - `app/routes/query_analysis_routes.py`
  - `app/routes/prompt_feedback.py`
  - `.claude/audits/backend-audit.md` (Task 6: query_studio_routes.py)
  - `src/features/query-forge/ui/QueryForgePage.tsx` (existence confirmed)
