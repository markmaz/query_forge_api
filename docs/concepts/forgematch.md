# ForgeMatch

## What it is

ForgeMatch is an assisted source-to-domain field mapping tool. Users upload a CSV or Excel file containing source schema fields, and ForgeMatch uses vector search and LLM-assisted ranking to suggest the best-matching workspace columns for each source field. Users review, accept, reject, or manually remap suggestions, then export results or draft a domain/view from accepted mappings.

## Why it matters

Mapping external data sources to QueryForge domains is time-consuming and error-prone when done manually. ForgeMatch automates the discovery phase, presenting ranked candidates so a human reviewer only needs to make final decisions — dramatically reducing the time to integrate new data sources.

## Who uses it

Users with the `forge_match:user` role (or `workspace_admin`). Requires the `forge_match` feature to be enabled in the workspace.

## Key concepts

### Session
A ForgeMatch session tracks one upload + analysis cycle. Sessions are persistent and identified by a `session_id` (string). A session moves through states: uploaded → analyzing → analyzed → (reviewed) → exported.

### Upload
`POST /api/v1/forge-match/upload` — multipart form-data with a `file` (CSV or Excel). Returns `session_id`, `uploaded_filename`, `sheet_count`, `source_record_count`, and a `source_preview`.

### Async Analysis
`POST /api/v1/forge-match/{session_id}/analyze/start` — starts an async Celery task. Returns `job_id`. Poll `GET /api/v1/forge-match/status/{job_id}` for progress (`queued|analyzing|analyzed|failed|canceled`, `current_phase`, `progress_pct`).

Synchronous analysis is also available: `POST /api/v1/forge-match/{session_id}/analyze`.

Cancel: `POST /api/v1/forge-match/cancel/{job_id}`.

### Analysis Pipeline (CODE_CONFIRMED from `app/services/forge_match/`)
The mapping service uses:
- `CandidateRetriever` — vector search against workspace column embeddings
- `LLMRanker` — LLM-assisted ranking of candidates
- `MappingService` — orchestrates retrieval, ranking, and persistence
- `ConfidenceScorer` — scores mapping confidence
- `Normalizer` — normalizes source field names

Analysis is now run through the shared_ai pipeline executor (Phase 4+ of the shared AI spec).

### Mappings Review
After analysis, mappings are retrieved via `GET /api/v1/forge-match/{session_id}`. Each mapping has:
- `mapping_id`
- Source field details
- Ranked candidate workspace columns
- Suggested match
- Status: `suggested | accepted | rejected | needs_review | manually_mapped`

Review actions via `PATCH /api/v1/forge-match/{session_id}/mappings`:
- `accept` — accept the suggested mapping
- `reject` — reject it
- `needs_review` — flag for further review
- `remap` — pick a different candidate (provide `manually_selected_workspace_column_id`)
- `edit_notes` — add review notes

### Export
`GET /api/v1/forge-match/{session_id}/export?format=csv|xlsx` — downloads accepted/reviewed mappings as a file.

### Draft Domain / View
- `POST /api/v1/forge-match/{session_id}/create-view-draft` — drafts a SQL view from accepted mappings
- `POST /api/v1/forge-match/{session_id}/create-domain-draft` — drafts a QueryForge domain definition from accepted mappings

### Session History
`GET /api/v1/forge-match` — lists sessions for the workspace (with search, status filter, pagination).
`GET /api/v1/forge-match/history?limit=n` — recent analyze runs.
`DELETE /api/v1/forge-match/{session_id}` — delete a session.

### Frontend Workflow
The ForgeMatch UI (at `/data-foundations/forge-match`) organizes work into stages: Upload → Extract → Analyze → Review → Finalize. It supports:
- Queue View (prioritized triage)
- Table View (power-user grid)
- Deep linking by `sessionId` and `jobId`

## Related features

- [Semantic Registry](semantic-registry.md)
- [Domains](domains.md)
- [User Guide: ForgeMatch Overview](../user-guides/forgematch-overview.md)
- [Task Playbook: Map a Spreadsheet](../task-playbooks/map-a-spreadsheet.md)

## Source grounding
- STATUS: CODE_CONFIRMED
- Sources:
  - `app/routes/forge_match_routes.py`
  - `app/services/forge_match/` (directory listing)
  - `src/features/forgeMatch/README.md`
  - `docs/forge_match_frontend_prompt.md`
