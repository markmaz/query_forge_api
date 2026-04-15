# Goal: Build Your First Query

## Audience

New analysts who have workspace access and at least one domain is configured.

## What you need

- `query_studio:user` role (or `workspace_admin`) in the target workspace
- Workspace `query_studio` feature enabled
- At least one domain with profile embeddings generated

## Steps

1. **Open Query Studio**
   Navigate to the Query Studio section of the application. (NEEDS_VERIFICATION: exact sidebar navigation label)

2. **Choose a domain**
   Select the domain that contains the data you want to query. If you are unsure, hover over domain names to see descriptions. The domain list is fetched from `GET /api/v1/domains/summary`.

3. **Type your question**
   Enter a natural language prompt. Be specific about what you want to measure and any filters. For example: "Show me chronic absenteeism rate by school for the current school year."

4. **Submit the prompt**
   Click Run (or equivalent button). The frontend calls the planner.

5. **Review the plan**
   The planner returns a structured plan showing which columns will be selected, which filters applied, and which groupings used. An explanation is shown describing the domain and concepts matched.

6. **Check suggested next actions**
   If next actions are enabled, the plan includes suggested follow-up queries. Review these for ideas.

7. **Execute the query**
   Click Execute (or equivalent). The frontend submits the compiled SQL for async execution and polls for results.

8. **View results**
   Results appear in a table. Note the total count and any pagination.

9. **Request AI analysis (optional)**
   Click "Analyze" (available after execution). The AI will generate a narrative summary of the results.

10. **Export (optional)**
    Click Export → Excel to download results.

## What happens next

You have a working query. From here you can:
- Save it for reuse (see [Save and Share a Query](save-and-share-query.md))
- Attach a Skill for automated monitoring (see [Skills concept](../concepts/skills.md))
- Create a ForgeMatch session if you have external data to map

## Common issues

- **Planner chooses the wrong domain** — add domain context to your prompt (e.g., name the domain explicitly), or see [troubleshooting/wrong-domain-selected.md](../troubleshooting/wrong-domain-selected.md).
- **No results returned** — the query may be too restrictive, or the data may be missing. See [troubleshooting/no-query-results.md](../troubleshooting/no-query-results.md).
- **503 from planner** — no LLM is configured for the workspace. See [troubleshooting/llm-failure.md](../troubleshooting/llm-failure.md).

## Related docs

- [First Query (getting started)](../getting-started/first-query.md)
- [Query Studio User Guide](../user-guides/query-studio.md)
- [Troubleshoot Planner Output](troubleshoot-planner-output.md)

## Source grounding
- STATUS: CODE_CONFIRMED (routes), NEEDS_VERIFICATION (UI flow details)
- Sources:
  - `app/routes/execution_routes.py`
  - `app/routes/query_analysis_routes.py`
  - `app/routes/export_routes.py`
