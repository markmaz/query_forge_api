# Goal: Map a Spreadsheet to QueryForge Columns

## Audience

Data integration analysts or domain administrators who need to map an external data file's fields to QueryForge workspace columns.

## What you need

- `forge_match:user` role (or `workspace_admin`)
- `forge_match` feature enabled in the workspace
- A CSV or Excel file with source field names (column headers)
- At least one domain with workspace tables and profile embeddings

## Steps

1. **Navigate to ForgeMatch**
   Go to `/data-foundations/forge-match` in the application.

2. **Upload your file**
   Drag-and-drop or use the file picker. Supported formats: CSV, Excel (.xlsx).
   The system returns: session_id, sheet count, source record count, and a preview.

3. **Configure analysis**
   Set:
   - **Top N** — number of candidate matches per field (3–20, default 8)
   - **Domain** — restrict to a specific domain (optional but recommended for better results)
   - **Vertical norm** — domain-specific normalization hint (optional)
   - **Force** — re-run even if previous analysis exists

4. **Start analysis**
   Click Analyze. The system submits an async job. A progress bar shows phases: extraction → retrieval → ranking.

5. **Wait for analysis to complete**
   Poll interval is 1.5 seconds. Terminal states: `analyzed`, `failed`, `canceled`.
   You can cancel mid-run if needed.

6. **Review mappings**
   After analysis, each source field shows ranked candidate workspace columns. Choose your review mode:
   - **Queue View** — work through fields in priority order
   - **Table View** — grid view for bulk review

   For each field, take one of these actions:
   - **Accept** — confirm the suggested top match
   - **Reject** — mark as unmappable
   - **Needs review** — defer for later
   - **Remap** — select a different candidate
   - **Edit notes** — add a comment

7. **Export or draft**
   When review is complete, choose a finalization action:
   - **Export CSV/Excel** — download the accepted mapping table
   - **Create View Draft** — generate a SQL view from accepted mappings
   - **Create Domain Draft** — generate a QueryForge domain definition

## What happens next

- An exported file gives you a portable mapping document.
- A view draft gives you a SQL view definition to deploy in your database.
- A domain draft gives you a QueryForge domain to configure and use in Query Studio.

## Common issues

- **Analysis fails** — check that the Celery worker is running (`GET /api/v1/admin/health/broker`). See [troubleshooting/agent-execution-issue.md](../troubleshooting/agent-execution-issue.md).
- **All candidates have low confidence** — try setting a specific domain to restrict the search space, or add more semantic concept column maps for the relevant domain.
- **Wrong candidates suggested** — review and update semantic concept column maps in the Semantic Admin.

## Related docs

- [Concepts: ForgeMatch](../concepts/forgematch.md)
- [User Guide: ForgeMatch Overview](../user-guides/forgematch-overview.md)
- [Troubleshoot: Mapping Ambiguity](../troubleshooting/mapping-ambiguity.md)

## Source grounding
- STATUS: CODE_CONFIRMED
- Sources:
  - `src/features/forgeMatch/README.md`
  - `app/routes/forge_match_routes.py`
  - `docs/forge_match_frontend_prompt.md`
