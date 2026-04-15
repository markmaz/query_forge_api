# ForgeMatch User Guide

## What it is

ForgeMatch helps you map source data file fields to QueryForge workspace columns using AI-assisted suggestions. Upload a spreadsheet, run analysis, review suggestions, and export or draft a domain from the results.

## Who uses it

Users with `forge_match:user` role (or `workspace_admin`) in a workspace where `forge_match` is entitled.

## Workflow

The ForgeMatch UI organizes work into five stages: **Upload → Extract → Analyze → Review → Finalize**.

### Stage 1: Upload

Go to `/data-foundations/forge-match` in the application. Drag-and-drop or use the file picker to upload a CSV or Excel file. After upload you see:
- File name
- Sheet count
- Source record count (number of source fields/rows)
- Source preview

### Stage 2: Extract

The system parses the file and extracts source field names and sample values. This happens automatically after upload.

### Stage 3: Analyze

Configure analysis parameters:
- **Top N** (3–20): how many candidate matches to consider per source field
- **Domain** (optional): restrict candidates to a specific domain
- **Vertical norm** (optional): a vertical normalization hint
- **Force re-analyze**: re-run even if results exist

Click "Analyze." The frontend starts an async job and shows a progress bar with phases (extraction → retrieval → ranking). You can cancel mid-run. Poll interval: 1.5s while running, stops on terminal state.

### Stage 4: Review

Once analysis is complete, the Review workspace shows source fields alongside ranked candidate matches. Two view modes:
- **Queue View** — prioritized master/detail triage
- **Table View** — power-user grid with sticky headers and row actions

For each source field you can:
- **Accept** — use the suggested match
- **Reject** — mark as no match
- **Needs review** — flag for later
- **Remap** — pick a different candidate from the ranked list
- **Edit notes** — add review comments

Manually remapped fields provide `manually_selected_workspace_column_id`.

### Stage 5: Finalize

Options available after review:
- **Export** — download accepted mappings as CSV or Excel
- **Create View Draft** — generates a SQL view definition from accepted mappings
- **Create Domain Draft** — drafts a QueryForge domain definition; returns `artifact_id`, `accepted_column_count`, and `columns`

## Session management

- Sessions are persistent and can be deep-linked: `/data-foundations/forge-match?sessionId=<id>`
- Active analyze runs can be deep-linked: `?sessionId=<id>&jobId=<job_id>`
- The Sessions pane lists all workspace sessions with search, status filter, and pagination

## Source grounding
- STATUS: CODE_CONFIRMED
- Sources:
  - `src/features/forgeMatch/README.md`
  - `app/routes/forge_match_routes.py`
  - `docs/forge_match_frontend_prompt.md`
