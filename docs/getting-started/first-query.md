# Goal: Run Your First Query

## Audience

New users who have been given access to a workspace with at least one domain configured.

## What you need

- An account with `query_studio:user` role (or `workspace_admin`) in the target workspace
- At least one domain configured in the workspace
- The workspace feature `query_studio` must be enabled

## Steps

1. **Navigate to Query Studio**
   Open the application and go to the Query Studio section. The frontend route is at the query-forge feature (`src/features/query-forge/`). NEEDS_VERIFICATION: exact navigation path in sidebar.

2. **Select a domain**
   The Query Studio presents available domains. The backend provides domain metadata via `GET /api/v1/domains/` (the `domains` namespace). Select the domain most relevant to your question.

3. **Enter a natural language prompt**
   Type your question in the prompt field, for example: "Show me attendance by school last month."

4. **Run the planner**
   Submit the prompt. The frontend calls `POST /api/v1/query-forge/plan` (NEEDS_VERIFICATION: exact route — see `app/routes/query_forge_routes.py`). The planner selects the domain, resolves semantic concepts, and returns a structured plan with SQL.

5. **Review and execute**
   The plan is shown with columns, filters, and groupings. The frontend calls `POST /api/v1/executions/start` to begin async execution, polls `GET /api/v1/executions/{job_id}/status` until complete, then fetches results from `GET /api/v1/executions/{job_id}/results`.

6. **Save your query (optional)**
   Once satisfied with the results, save the query to the query tree using the save option. This calls `POST /api/v1/query-tree/queries` (NEEDS_VERIFICATION: exact route path).

## What happens next

Query results are displayed in a table. You can export to Excel via `POST /api/v1/exports/excel`, add an AI analysis via the "Analyze" button (which calls `POST /api/v1/query_analysis/{query_id}/analyze`), or attach a Skill to the saved query for automated monitoring.

## Common issues

- **No domains visible** — the workspace has no domains configured. An admin must create a domain in Domain Studio first.
- **Plan returns wrong domain** — see [troubleshooting/wrong-domain-selected.md](../troubleshooting/wrong-domain-selected.md).
- **No results** — see [troubleshooting/no-query-results.md](../troubleshooting/no-query-results.md).
- **LLM failure / 503** — see [troubleshooting/llm-failure.md](../troubleshooting/llm-failure.md).

## Related docs

- [Query Studio user guide](../user-guides/query-studio.md)
- [Planner concept](../concepts/planner.md)
- [Troubleshoot planner output](../task-playbooks/troubleshoot-planner-output.md)

## Source grounding
- STATUS: CODE_CONFIRMED (routes), NEEDS_VERIFICATION (exact UI flow)
- Sources:
  - `app/routes/query_forge_routes.py` (QueryForgeRun, QueryForgePlan)
  - `app/routes/execution_routes.py`
  - `app/routes/export_routes.py`
  - `app/routes/query_analysis_routes.py`
  - `src/features/query-forge/ui/QueryForgePage.tsx` (existence confirmed)
