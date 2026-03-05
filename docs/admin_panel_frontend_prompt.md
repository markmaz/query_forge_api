# Admin Panel Frontend Prompt

## Overview

Build a **React Admin Panel** (single-page application) for the Query Forge API backend. The panel provides four main features:

1. **System Health Dashboard** — real-time status of Flask API, MySQL, vLLM (Qwen LLM), and Qdrant
2. **Pipeline Profiling** — view recent planner pipeline timing data with charts
3. **Vector Index Management** — rebuild/reindex Qdrant vector indexes in the correct order
4. **Domain Profile Management** — full CRUD for domain profile records

---

## Tech Stack Requirements

- **React 18+** with TypeScript
- **Routing**: React Router v6
- **State management**: React Query (TanStack Query) for server state
- **Charts**: Recharts (bar charts, pie charts, line charts)
- **UI framework**: Tailwind CSS + shadcn/ui (or similar component library)
- **HTTP client**: Axios or fetch wrapper
- **Icons**: Lucide React

---

## Authentication

All admin endpoints require:
- `Authorization: Bearer <jwt_token>` header
- `X-Workspace-Id: <workspace_id>` header (for workspace-scoped endpoints)
- The authenticated user must have `is_admin: true` in their JWT claims

The API returns `403` with `{"error": "Admin access required"}` if the user is not an admin.

Implement an API client wrapper that:
- Attaches the auth token and workspace ID to every request
- Handles 401 (redirect to login) and 403 (show "access denied")
- Includes error toast notifications for failed requests

---

## API Base URL

All endpoints are under: `{API_BASE_URL}/api/v1/admin/`

Configure `API_BASE_URL` via environment variable (e.g., `VITE_API_BASE_URL`).

---

## Feature 1: System Health Dashboard

### Page: `/admin/health`

**Endpoint:** `GET /api/v1/admin/health/detailed`

**Headers:** `Authorization`, `X-Workspace-Id`

**Response (200 when healthy, 503 when degraded/unhealthy):**
```json
{
  "overall": "healthy" | "degraded" | "unhealthy",
  "checks": {
    "app": {
      "status": "ok"
    },
    "mysql": {
      "status": "ok" | "error",
      "latency_ms": 5,
      "error": "optional error message"
    },
    "vllm": {
      "status": "ok" | "error",
      "latency_ms": 120,
      "model": "qwen25-7b",
      "upstream": { "data": [{ "id": "qwen25-7b" }] },
      "error": "optional error message"
    },
    "qdrant": {
      "status": "ok" | "error",
      "latency_ms": 8,
      "error": "optional error message"
    }
  }
}
```

### UI Requirements

1. **Overall Status Banner**: Large colored banner at top:
   - Green = "healthy" (all services up)
   - Yellow = "degraded" (some services down)
   - Red = "unhealthy" (all external services down)

2. **Service Status Cards** (grid of 4 cards):
   Each card shows:
   - Service name (Flask App, MySQL Database, Qwen LLM (vLLM), Qdrant Vector DB)
   - Status icon (green checkmark / red X)
   - Latency in ms (where available)
   - Model name (for vLLM only)
   - Error message (if status is "error"), shown in a collapsible section

3. **Latency Bar Chart**: Horizontal bar chart comparing latency_ms across MySQL, vLLM, and Qdrant. Color-code bars: green < 100ms, yellow 100-500ms, red > 500ms.

4. **Auto-refresh**: Poll the health endpoint every 30 seconds. Show a "Last checked: X seconds ago" timestamp. Include a manual "Refresh Now" button.

5. **History** (optional enhancement): Keep last 20 health check results in local state, render a line chart showing latency trends over time for each service.

---

## Feature 2: Pipeline Profiling

### Page: `/admin/pipeline-profiles`

**List Endpoint:** `GET /api/v1/admin/pipeline-profiles?limit=50`

**Headers:** `Authorization`, `X-Workspace-Id`

**Response:**
```json
{
  "profiles": [
    {
      "trace_id": "c10ff1b7-7d15-45e1-aac2-eb8b5203c733",
      "workspace_id": "ws-1",
      "user_id": "user-1",
      "conversation_id": "pdc_6fc78432d83f4bd993e0",
      "total_ms": 1049,
      "timestamp": "2026-03-04 13:58:10,159",
      "prompt": "show me attendance by school",
      "steps": [
        { "index": 1, "label": "Load and prepare conversation context", "ms": 5 },
        { "index": 2, "label": "Normalize prompt and effective vertical", "ms": 2 },
        { "index": 3, "label": "Select candidate domains from vector index", "ms": 45 },
        { "index": 4, "label": "Load capabilities, shortlist columns", "ms": 120 },
        { "index": 5, "label": "LLM plan generation", "ms": 750 },
        { "index": 6, "label": "Validate and repair plan", "ms": 80 },
        { "index": 7, "label": "Map plan to SQL JSON", "ms": 47 }
      ]
    }
  ],
  "count": 1
}
```

**Single Profile Endpoint:** `GET /api/v1/planner/plan_domain/profile/{trace_id}`

**Headers:** `Authorization`, `X-Workspace-Id`

**Response:**
```json
{
  "trace_id": "c10ff1b7-...",
  "workspace_id": "ws-1",
  "user_id": "user-1",
  "conversation_id": "pdc_...",
  "total_ms": 1049,
  "timestamp": "2026-03-04 13:58:10,159",
  "prompt": "show me attendance by school",
  "steps": [
    { "index": 1, "label": "Load and prepare conversation context", "ms": 5 },
    { "index": 2, "label": "Normalize prompt and effective vertical", "ms": 2 },
    { "index": 3, "label": "Select candidate domains from vector index", "ms": 45 },
    { "index": 4, "label": "Load capabilities", "ms": 120 },
    { "index": 5, "label": "LLM plan generation", "ms": 750 },
    { "index": 6, "label": "Validate and repair plan", "ms": 80 },
    { "index": 7, "label": "Map plan to SQL JSON", "ms": 47 }
  ],
  "log_file": "logs/plan_domain_pipeline_timing.log",
  "profiling_enabled": true
}
```

### UI Requirements

1. **Profile Table**: Sortable, paginated table showing:
   - Timestamp
   - Trace ID (truncated, copy-to-clipboard on click)
   - Prompt (truncated to ~60 chars with tooltip for full text)
   - Total ms (with color coding: green < 500ms, yellow 500-2000ms, red > 2000ms)
   - User ID
   - Conversation ID

2. **Click to expand**: Clicking a row opens a detail view showing:
   - Full prompt text
   - All metadata (trace_id, workspace_id, user_id, conversation_id)
   - **Stacked Horizontal Bar Chart**: Each pipeline step as a segment, showing what % of total time each step took. Use distinct colors per step category. Show ms values on hover.
   - **Waterfall / Gantt Chart**: Steps laid out sequentially showing cumulative timing.
   - **Step Table**: Ordered list of steps with index, label, ms, and % of total.

3. **Aggregate Statistics** (top of page):
   - Average total_ms across all loaded profiles
   - Median total_ms
   - P95 total_ms
   - A **Pie Chart** showing average time distribution across step categories (Domain Selection, Capabilities, LLM, Validation, Map to SQL JSON)

4. **Filters**: Optional filter by date range and user_id.

5. **Limit control**: Dropdown to select limit (10, 25, 50, 100).

---

## Feature 3: Vector Index Management

### Page: `/admin/vector-indexes`

**Endpoints:**

| Action | Method | URL | Request Body | Response |
|--------|--------|-----|-------------|----------|
| Rebuild All | POST | `/api/v1/admin/vector/rebuild-all` | `{ "vertical_norm": "education", "force": false }` | See below |
| Rebuild Semantic Concepts | POST | `/api/v1/admin/vector/semantic-concepts/rebuild` | `{ "vertical_norm": "education" }` | `{ "result": { "conceptPoints": N, "aliasPoints": N }, "vertical_norm": "..." }` |
| Reindex Domain Vectors | POST | `/api/v1/admin/vector/domains/reindex` | `{ "vertical_norm": "education", "force": false }` | `{ "result": { "upserted": N, "skipped": N, "total": N, "timings_ms": {...}, "collection": "..." } }` |
| Rebuild Embeddings | POST | `/api/v1/admin/vector/embeddings/rebuild` | `{ "include_tables": true, "limit": 0 }` | `{ "result": { "tablesIndexed": N, "columnsIndexed": N } }` |

All require `Authorization` and `X-Workspace-Id` headers.

**Rebuild All Response:**
```json
{
  "status": "completed" | "completed_with_errors",
  "results": {
    "semantic_concepts": { "conceptPoints": 150, "aliasPoints": 80 },
    "embeddings": { "tablesIndexed": 25, "columnsIndexed": 1200 },
    "domain_vectors": { "upserted": 10, "skipped": 0, "total": 10 }
  },
  "errors": {},
  "workspace_id": "ws-1",
  "vertical_norm": "education"
}
```

When errors occur:
```json
{
  "status": "completed_with_errors",
  "results": {
    "semantic_concepts": { "conceptPoints": 150, "aliasPoints": 80 }
  },
  "errors": {
    "embeddings": "Connection refused",
    "domain_vectors": "Qdrant timeout"
  },
  "workspace_id": "ws-1",
  "vertical_norm": "education"
}
```

### UI Requirements

1. **Index Overview Cards** (grid of 4 cards):
   - **Semantic Concepts** — concepts + aliases from semantic registry
   - **Table Catalog** — model tables for search
   - **Column Catalog** — workspace columns for search
   - **Domain Vectors** — domain profiles for planner routing

   Each card shows:
   - Index name and description
   - A "Rebuild" button (individual rebuild)
   - Last rebuild result (if just rebuilt in this session)
   - Status indicator (idle / building / completed / error)

2. **Rebuild All Button**: Prominent button at top. When clicked:
   - Shows a confirmation dialog with options:
     - `vertical_norm` text input (default: "education")
     - `force` checkbox (default: unchecked)
   - Displays a progress stepper showing: Step 1: Semantic Concepts → Step 2: Table & Column Embeddings → Step 3: Domain Vectors
   - Each step updates its status (pending → building → completed / error)
   - On completion, shows summary with counts

3. **Build Order Visualization**: A small diagram or numbered list explaining the rebuild order:
   1. Semantic Concepts (independent)
   2. Table & Column Embeddings (independent)
   3. Domain Vectors (benefits from fresh profiles)

4. **Result Details**: After any rebuild, show:
   - Items indexed/upserted per category
   - Timing information (where returned)
   - Error details (collapsible, red highlighted)

5. **Loading states**: Disable all rebuild buttons while any rebuild is in progress. Show spinner and elapsed time.

---

## Feature 4: Domain Profile Management

### Page: `/admin/domain-profiles`

**Endpoints:**

| Action | Method | URL | Request Body |
|--------|--------|-----|-------------|
| List | GET | `/api/v1/admin/domain-profiles` | — |
| Get | GET | `/api/v1/admin/domain-profiles/{domain_id}` | — |
| Create | POST | `/api/v1/admin/domain-profiles` | See below |
| Update | PUT | `/api/v1/admin/domain-profiles/{domain_id}` | See below |
| Delete | DELETE | `/api/v1/admin/domain-profiles/{domain_id}` | — |

All require `Authorization` and `X-Workspace-Id` headers.

**List Response:**
```json
{
  "profiles": [
    {
      "id": 1,
      "workspace_id": "927164193773577",
      "domain_id": 4,
      "summary": "Organizational structure and attributes for districts, schools, and education organizations.",
      "keywords": ["schools", "districts", "education organizations", "organization hierarchy"],
      "entities": ["education_organization", "district", "school", "charter", "location"],
      "metrics": ["enrollment_count_by_school", "staff_count_by_school"],
      "attributes": ["education_organization_id", "school_id", "district_id", "school_name"],
      "synonyms": [
        { "term": "org", "means": ["organization", "education organization"] },
        { "term": "lea", "means": ["district", "local education agency"] }
      ],
      "acronyms": [
        { "abbr": "LEA", "expansion": "Local Education Agency" },
        { "abbr": "SEA", "expansion": "State Education Agency" }
      ],
      "notes": "Used for grouping and joins across student and staff domains.",
      "embedding_text": "Domain: Schools, Districts & Organizations\nKind: Schools\n...",
      "content_hash": "a1b2c3d4...",
      "embedding_model": null,
      "embedded_at": null,
      "created_at": "2026-01-15 10:30:00",
      "updated_at": "2026-02-20 14:15:00",
      "domain_name": "Schools, Districts & Organizations"
    }
  ],
  "count": 1
}
```

**Create Request Body:**
```json
{
  "domain_id": 4,
  "summary": "Domain summary text",
  "keywords": ["keyword1", "keyword2"],
  "entities": ["entity1", "entity2"],
  "metrics": ["metric1"],
  "attributes": ["attr1", "attr2"],
  "synonyms": [{ "term": "short", "means": ["full term"] }],
  "acronyms": [{ "abbr": "ABC", "expansion": "Alpha Beta Charlie" }],
  "notes": "Optional notes",
  "embedding_text": "Optional custom embedding text (auto-generated if omitted)"
}
```

**Update Request Body** (partial update — only include fields to change):
```json
{
  "summary": "Updated summary",
  "keywords": ["new", "keywords"]
}
```

**Delete Response:**
```json
{
  "deleted": true,
  "workspace_id": "ws-1",
  "domain_id": 4
}
```

### UI Requirements

1. **Profile List Table**: Sortable table showing:
   - Domain Name (from `domain_name`)
   - Domain ID
   - Summary (truncated)
   - Keywords (as tags/chips, max 5 shown with "+N more")
   - Entities count
   - Metrics count
   - Last Updated timestamp
   - Actions: Edit | Delete

2. **Create / Edit Form** (modal or separate page):
   - **Domain ID**: Number input (required for create, read-only for edit)
   - **Summary**: Textarea
   - **Keywords**: Tag input (add/remove individual keywords)
   - **Entities**: Tag input
   - **Metrics**: Tag input
   - **Attributes**: Tag input
   - **Synonyms**: Dynamic list of rows, each with:
     - `term` (text input)
     - `means` (tag input for array of meanings)
     - Remove row button
     - Add row button
   - **Acronyms**: Dynamic list of rows, each with:
     - `abbr` (text input)
     - `expansion` (text input)
     - Remove row button
     - Add row button
   - **Notes**: Textarea
   - **Embedding Text**: Textarea (collapsible/advanced section). Show "Auto-generated if left empty" hint.
   - **Content Hash**: Read-only display (on edit form only)
   - **Save** and **Cancel** buttons

3. **Delete Confirmation**: Modal dialog: "Are you sure you want to delete the profile for domain '{domain_name}' (ID: {domain_id})?"

4. **After Create/Update**: Show success toast. Optionally prompt "Would you like to rebuild domain vector indexes to reflect this change?" with a button that triggers `POST /api/v1/admin/vector/domains/reindex`.

5. **Validation**:
   - `domain_id` is required and must be > 0 for create
   - `summary` should not be empty
   - Keywords/entities/metrics must be non-empty strings

---

## Navigation & Layout

### Sidebar Navigation
- **Dashboard** → `/admin/health`
- **Pipeline Profiles** → `/admin/pipeline-profiles`
- **Vector Indexes** → `/admin/vector-indexes`
- **Domain Profiles** → `/admin/domain-profiles`

### Top Bar
- Application title: "Query Forge Admin"
- Current workspace ID display
- User info / logout button
- Connection indicator (green/red dot based on last health check)

### Responsive Design
- Desktop-first but responsive down to tablet (1024px min)
- Sidebar collapses to icons on smaller screens

---

## Error Handling

All API error responses follow this format:
```json
{
  "error": "Human-readable error message",
  "status_code": 400 | 403 | 404 | 409 | 500,
  "details": { ... }
}
```

Handle:
- **401**: Token expired → redirect to login
- **403**: Not admin → show "Access Denied" page
- **404**: Resource not found → show "Not Found" message
- **409**: Conflict (e.g., domain profile already exists) → show specific message
- **500**: Server error → show generic error with retry option

---

## Color Palette & Theming

Use a professional dark-mode-capable theme:
- Primary: Blue (#3B82F6)
- Success: Green (#22C55E)
- Warning: Yellow/Amber (#F59E0B)
- Error: Red (#EF4444)
- Background: White / Slate-50 (light) or Slate-900 (dark)
- Cards: White / Slate-800 with subtle shadows

---

## File Structure (suggested)

```
src/
├── api/
│   ├── client.ts              # Axios instance with auth interceptors
│   ├── adminHealth.ts         # Health check API calls
│   ├── pipelineProfiles.ts    # Pipeline profile API calls
│   ├── vectorIndexes.ts       # Vector rebuild API calls
│   └── domainProfiles.ts      # Domain profile CRUD API calls
├── components/
│   ├── layout/
│   │   ├── AdminLayout.tsx    # Sidebar + top bar + main content
│   │   ├── Sidebar.tsx
│   │   └── TopBar.tsx
│   ├── health/
│   │   ├── HealthDashboard.tsx
│   │   ├── ServiceCard.tsx
│   │   ├── LatencyChart.tsx
│   │   └── StatusBanner.tsx
│   ├── profiles/
│   │   ├── ProfileList.tsx
│   │   ├── ProfileDetail.tsx
│   │   ├── StepChart.tsx
│   │   └── AggregateStats.tsx
│   ├── vectors/
│   │   ├── VectorIndexPage.tsx
│   │   ├── IndexCard.tsx
│   │   ├── RebuildAllDialog.tsx
│   │   └── RebuildProgress.tsx
│   └── domain-profiles/
│       ├── DomainProfileList.tsx
│       ├── DomainProfileForm.tsx
│       ├── TagInput.tsx
│       ├── SynonymEditor.tsx
│       └── AcronymEditor.tsx
├── hooks/
│   ├── useHealthCheck.ts
│   ├── usePipelineProfiles.ts
│   ├── useVectorRebuild.ts
│   └── useDomainProfiles.ts
├── types/
│   ├── health.ts
│   ├── pipelineProfile.ts
│   ├── vectorIndex.ts
│   └── domainProfile.ts
├── pages/
│   ├── HealthPage.tsx
│   ├── PipelineProfilesPage.tsx
│   ├── VectorIndexesPage.tsx
│   └── DomainProfilesPage.tsx
├── App.tsx
└── main.tsx
```

---

## TypeScript Types

```typescript
// health.ts
interface HealthCheck {
  overall: "healthy" | "degraded" | "unhealthy";
  checks: {
    app: ServiceCheck;
    mysql: ServiceCheck;
    vllm: VllmCheck;
    qdrant: ServiceCheck;
  };
}

interface ServiceCheck {
  status: "ok" | "error";
  latency_ms?: number;
  error?: string;
}

interface VllmCheck extends ServiceCheck {
  model?: string;
  upstream?: Record<string, unknown>;
}

// pipelineProfile.ts
interface PipelineProfile {
  trace_id: string;
  workspace_id: string;
  user_id: string;
  conversation_id: string;
  total_ms: number;
  timestamp: string;
  prompt: string;
  steps: PipelineStep[];
}

interface PipelineStep {
  index: number;
  label: string;
  ms: number;
}

interface PipelineProfileListResponse {
  profiles: PipelineProfile[];
  count: number;
}

// vectorIndex.ts
interface RebuildAllRequest {
  vertical_norm?: string;
  force?: boolean;
}

interface RebuildAllResponse {
  status: "completed" | "completed_with_errors";
  results: {
    semantic_concepts?: { conceptPoints: number; aliasPoints: number };
    embeddings?: { tablesIndexed: number; columnsIndexed: number };
    domain_vectors?: { upserted: number; skipped: number; total: number };
  };
  errors: Record<string, string>;
  workspace_id: string;
  vertical_norm: string;
}

interface SemanticConceptRebuildResponse {
  result: { conceptPoints: number; aliasPoints: number };
  vertical_norm: string;
}

interface EmbeddingsRebuildResponse {
  result: { tablesIndexed: number; columnsIndexed: number };
}

interface DomainVectorReindexResponse {
  result: {
    upserted: number;
    skipped: number;
    total: number;
    timings_ms?: Record<string, number>;
    collection?: string;
  };
}

// domainProfile.ts
interface DomainProfile {
  id: number;
  workspace_id: string;
  domain_id: number;
  summary: string | null;
  keywords: string[] | null;
  entities: string[] | null;
  metrics: string[] | null;
  attributes: string[] | null;
  synonyms: Synonym[] | null;
  acronyms: Acronym[] | null;
  notes: string | null;
  embedding_text: string | null;
  content_hash: string | null;
  embedding_model: string | null;
  embedded_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  domain_name: string | null;
}

interface Synonym {
  term: string;
  means: string[];
}

interface Acronym {
  abbr: string;
  expansion: string;
}

interface DomainProfileCreateRequest {
  domain_id: number;
  summary?: string;
  keywords?: string[];
  entities?: string[];
  metrics?: string[];
  attributes?: string[];
  synonyms?: Synonym[];
  acronyms?: Acronym[];
  notes?: string;
  embedding_text?: string;
}

interface DomainProfileUpdateRequest {
  summary?: string;
  keywords?: string[];
  entities?: string[];
  metrics?: string[];
  attributes?: string[];
  synonyms?: Synonym[];
  acronyms?: Acronym[];
  notes?: string;
  embedding_text?: string;
}

interface DomainProfileListResponse {
  profiles: DomainProfile[];
  count: number;
}

interface DomainProfileDeleteResponse {
  deleted: boolean;
  workspace_id: string;
  domain_id: number;
}
```

---

## API Error Type

```typescript
interface ApiError {
  error: string;
  status_code: number;
  details: Record<string, unknown>;
}
```
