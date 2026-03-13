# Codex Prompt: Implement ForgeMatch V1 Frontend (React + Bootstrap)

You are working in QueryForge frontend.

## Goal
Build a production-ready ForgeMatch review workflow UI for assisted source-to-QueryForge field mapping.

## Backend endpoints (already available)
All endpoints require auth and `X-Workspace-Id`.

- `POST /api/v1/forge-match/upload`
  - Multipart form-data with `file` (`.csv` or `.xlsx`)
- `POST /api/v1/forge-match/{session_id}/analyze`
  - JSON body:
    - `top_n` (default 8)
    - `domain_id` (optional)
    - `vertical_norm` (optional)
    - `force` (default false)
- `POST /api/v1/forge-match/{session_id}/analyze/start`
  - Starts async analysis run (preferred for status bar flow)
  - Same JSON body as `analyze`
  - Returns:
    - `job_id`
    - `session_id`
    - `workspace_id`
    - `status` (`queued`)
    - `source_total`
- `GET /api/v1/forge-match/status/{job_id}`
  - Poll run state/progress for status bar.
  - Response fields include:
    - `status` (`queued|analyzing|analyzed|failed|canceled`)
    - `current_phase`
    - `current_source_row_id`
    - `source_total`
    - `source_done`
    - `source_skipped`
    - `source_failed`
    - `progress_pct`
    - `analysis_error`
- `POST /api/v1/forge-match/cancel/{job_id}`
  - Cancels queued/running analysis.
- `GET /api/v1/forge-match/history?limit=20`
  - Returns recent analyze runs for workspace.
- `GET /api/v1/admin/health/broker`
  - Admin-only broker diagnostics for troubleshooting queue issues.
  - Response includes:
    - `ok`
    - `broker_url` (masked)
    - `valkey.ping_ok`
    - `celery.broker_connect_ok`
    - `celery.worker_ping_ok`
    - `celery.workers[]`
- `GET /api/v1/forge-match/{session_id}`
  - Query params:
    - `source_limit`, `source_offset`
    - `mapping_limit`, `mapping_offset`
- `PATCH /api/v1/forge-match/{session_id}/mappings`
  - JSON body:
    - `updates: [{ mapping_id, action?, status?, manually_selected_workspace_column_id?, review_notes? }]`
  - `action` values:
    - `accept`, `reject`, `needs_review`, `remap`, `edit_notes`
  - `status` values:
    - `suggested`, `accepted`, `rejected`, `needs_review`, `manually_mapped`
- `GET /api/v1/forge-match/{session_id}/export?format=csv|xlsx`
- `POST /api/v1/forge-match/{session_id}/create-view-draft`
  - JSON: `{ "name": "optional" }`
- `POST /api/v1/forge-match/{session_id}/create-domain-draft`
  - JSON: `{ "name": "optional" }`

## UX requirements
1. Add new page: `Data Foundations -> ForgeMatch`.
2. Step 1: Upload panel
   - Drag/drop + file picker for csv/xlsx.
   - Show file name, upload progress, parse summary (sheet count, source record count).
3. Step 2: Analyze panel
   - Controls: `Top N` (3-20), optional `Domain` selector, `Force re-analyze` toggle.
   - Trigger `POST /analyze/start`, store `job_id`, and drive existing status bar from `GET /status/{job_id}` polling.
   - Poll interval:
     - 1.5s while `queued|analyzing`
     - stop on `analyzed|failed|canceled`
   - Support Cancel button bound to `POST /cancel/{job_id}`.
   - Add a small “Queue Health” indicator near the status bar:
     - green when diagnostics `ok === true`
     - red when false
     - tooltip/popover shows `valkey` and `celery` diagnostics details
   - Poll diagnostics every 15s while user is on ForgeMatch page, and on Analyze click before enqueue.
   - On terminal success (`analyzed`), refetch `GET /forge-match/{session_id}` for grid data.
4. Step 3: Review grid
   - Columns:
     - Source field
     - Description
     - Type
     - Best match (table.column)
     - Alternates (up to 2)
     - Confidence (score + band badge)
     - Decision (`matched|ambiguous|no_confident_match`)
     - Status
     - Explanation
     - Actions
   - Row actions:
     - Accept
     - Reject
     - Needs review
     - Remap (manual column picker)
     - Edit notes
5. Manual remap UX
   - Open a modal with a searchable column picker.
   - Save via PATCH with `action: "remap"` and `manually_selected_workspace_column_id`.
6. Filters and quick stats
   - Summary cards from `summary` response:
     - total
     - status_counts
     - decision_counts
     - confidence_bands
   - Table filters for status, confidence band, and search text.
7. Export actions
   - Buttons: Export CSV, Export XLSX.
   - Open endpoint in browser/download flow.
8. Draft actions
   - Buttons: Create View Draft, Create Domain Draft.
   - Prompt for optional name.
   - Show returned artifact id + summary toast.

## API client requirements
- Add `forgeMatchApi.ts` module with typed functions:
  - `uploadForgeMatchFile(file)`
  - `analyzeForgeMatch(sessionId, body)`
  - `startForgeMatchAnalyze(sessionId, body)`
  - `getForgeMatchAnalyzeStatus(jobId)`
  - `cancelForgeMatchAnalyze(jobId)`
  - `getForgeMatchAnalyzeHistory(limit?)`
  - `getAdminBrokerDiagnostics()`
  - `getForgeMatchSession(sessionId, params)`
  - `patchForgeMatchMappings(sessionId, updates)`
  - `exportForgeMatch(sessionId, format)`
  - `createForgeMatchViewDraft(sessionId, body)`
  - `createForgeMatchDomainDraft(sessionId, body)`
- Preserve existing auth token + workspace header wiring.

## State management
- Use React Query for all server interactions.
- Cache key: `['forge-match', sessionId, sourceOffset, mappingOffset, filters]`.
- Invalidate session query after patch/update/analyze actions.
- Add run status cache key: `['forge-match-run', jobId]`.
- Add broker diagnostics cache key: `['forge-match-broker-diagnostics']`.
- Keep `activeForgeMatchJobId` in page state or URL param so status survives navigation refresh.

## Component design
- `ForgeMatchPage`
- `ForgeMatchUploadCard`
- `ForgeMatchAnalyzeControls`
- `ForgeMatchSummaryCards`
- `ForgeMatchReviewTable`
- `ForgeMatchRemapModal`
- `ForgeMatchNotesModal`

## Visual style (modern)
- Use Bootstrap layout but with modern styling tokens:
  - soft card shadows
  - pill badges for confidence/status
  - sticky table header
  - compact row density toggle
- Confidence badge colors:
  - high: green
  - medium: amber
  - low: red

## Validation / safety
- Disable destructive actions while mutation pending.
- Guard remap: require a selected column id.
- Show backend validation errors inline/toast.

## Tests
- Unit tests for API client payloads.
- Component tests for:
  - upload -> analyze/start -> status polling -> table render
  - status bar renders `progress_pct`, phase text, and terminal state badges
  - cancel action calls `/cancel/{job_id}` and updates status bar state
  - accept/reject/remap actions firing PATCH payloads
  - export button URLs
- Route guard test: only authenticated users can access page.

## Acceptance criteria
1. User can upload csv/xlsx and receive a session.
2. User can analyze and review full mapping results.
3. User can accept/reject/needs_review/remap/edit notes.
4. User can export csv/xlsx.
5. User can create view/domain drafts from accepted mappings.
6. All frontend tests pass.
