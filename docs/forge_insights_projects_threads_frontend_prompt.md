# ForgeInsights Frontend Prompt (Projects + Threads)

Copy/paste this prompt into your frontend coding assistant:

```text
Implement full ForgeInsights Projects + Threads UX against these backend APIs.

Base requirements:
- Use these headers on every request:
  - Authorization: Bearer <token>
  - X-Workspace-Id: <workspaceId>
- Never send user_id/workspace_id in request body.
- Treat this as ChatGPT-style left-nav with Projects and Threads.

API endpoints:
- GET    /api/v1/forge-insights/projects?include_archived=false
- POST   /api/v1/forge-insights/projects
- GET    /api/v1/forge-insights/projects/:projectId
- PATCH  /api/v1/forge-insights/projects/:projectId
- DELETE /api/v1/forge-insights/projects/:projectId
- GET    /api/v1/forge-insights/threads?project_id=<id>&include_archived=false&limit=50&offset=0
- POST   /api/v1/forge-insights/threads
- GET    /api/v1/forge-insights/threads/:threadId
- PATCH  /api/v1/forge-insights/threads/:threadId
- DELETE /api/v1/forge-insights/threads/:threadId
- Chat endpoint remains:
  - POST /api/v1/chat/forge-insights

Data contracts:
- Project:
  - id, name, description, is_archived, created_at, updated_at
- Thread:
  - id, project_id, conversation_id, title, preview_text, is_pinned, is_archived, last_message_at, created_at, updated_at
- Thread create can omit conversation_id; backend returns generated conversation_id.

UI behavior:
1) Left navigation:
   - Project list (collapsible)
   - Thread list under selected project and an “Unassigned” bucket (project_id null)
2) Create Project:
   - Inline input + optimistic insert.
3) Create Thread:
   - On “New chat”, call POST /threads with selected project_id and optional title.
   - Save returned thread.id + conversation_id as active thread context.
4) Open Thread:
   - GET /threads/:threadId, then load chat messages using that thread’s conversation_id.
5) Send message:
   - POST /chat/forge-insights with conversation_id + new user message.
   - On assistant response, PATCH /threads/:threadId with:
     - preview_text (latest assistant summary snippet),
     - last_message_at (new Date().toISOString()).
   - If title is empty and this is first prompt, set title from first user message (truncate ~80 chars) via PATCH.
6) Move thread between projects:
   - PATCH /threads/:threadId { project_id: newProjectId }.
7) Archive:
   - PATCH project/thread with is_archived=true instead of delete for normal UX.
   - Keep delete action in overflow menu for permanent removal.
8) Pinned threads:
   - Toggle with PATCH /threads/:threadId { is_pinned: true|false }.
   - Render pinned threads at top.
9) Expired conversation handling:
   - If chat endpoint returns 404 for conversation_id, create a new thread in same project and retry once.

Frontend architecture:
- Build a typed API client module: forgeInsightsApi.ts
- Build hooks:
  - useForgeInsightsProjects(workspaceId)
  - useForgeInsightsThreads(workspaceId, selectedProjectId)
  - useForgeInsightsChatThread(activeThread)
- Global state (Zustand/Redux/Context):
  - selectedProjectId
  - activeThreadId
  - activeConversationId
- Persist selectedProjectId + activeThreadId per workspace in localStorage.

TypeScript types:
- ForgeInsightsProject
- ForgeInsightsThread
- ForgeInsightsChatRequest
- ForgeInsightsChatResponse

Quality requirements:
- Fully typed request/response parsing.
- Optimistic updates with rollback on API failure.
- Toast/banner errors; don’t clear user draft on failure.
- Skeleton states for left-nav and conversation panel.
- Unit tests for:
  - create/move/archive thread
  - chat send updates preview/last_message_at
  - retry flow when conversation_id is stale
```

