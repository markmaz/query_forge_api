# ForgeInsights Frontend Prompt (Render Execution Results In Chat)

Copy/paste this into your frontend coding assistant:

```text
Implement ForgeInsights chat result rendering so education-pipeline query results appear as assistant chat messages.

Context:
- POST /api/v1/chat/forge-insights may return:
  - mode = "education_pipeline"
  - execution.jobId
  - message.content (initial summary)
- Then frontend should poll:
  - GET /api/v1/executions/:jobId/status
  - GET /api/v1/executions/:jobId/results when status == SUCCEEDED
- /executions/:jobId/results now includes:
  - assistant_message: { role, content, format, kind }
    - kind = "execution_result"
    - format = "markdown"
    - content includes summary + markdown table preview

Requirements:
1) Preserve existing chat send flow to /chat/forge-insights.
2) If response.mode == "education_pipeline" and execution.jobId exists:
   - Append the returned `message` immediately as assistant bubble.
   - Create a pending execution state tied to that assistant bubble.
3) Poll execution status every 1.5s (max 60s, exponential backoff allowed).
4) On SUCCEEDED:
   - Fetch /executions/:jobId/results
   - If `assistant_message` exists, append it as a new assistant chat message.
   - Also render a structured table view from `rows` + `columns` under the same bubble (optional toggle).
5) On RUNNING timeout:
   - Show a retry button on the pending bubble.
6) On FAILED:
   - Append assistant error bubble: “The query failed. Try rephrasing or running again.”
7) Keep conversation_id and thread metadata behavior unchanged.

TypeScript contracts:
- ForgeInsightsChatResponse:
  - mode?: "chat" | "education_pipeline"
  - message?: { role: "assistant"; content: string }
  - execution?: { jobId: string; statementId?: string }
- ExecutionResultsResponse:
  - rows: Record<string, unknown>[]
  - columns: { key: string; label?: string; dataType?: string }[]
  - total: number
  - assistant_message?: {
      role: "assistant"
      content: string
      kind: "execution_result"
      format: "markdown"
    }

UI rules:
- Chat renderer should support markdown for assistant messages.
- For assistant_message.kind === "execution_result", show:
  - markdown content
  - collapsible raw table below
  - “rows returned” badge
- Do not block user from sending another prompt while previous execution is running.

Implementation shape:
- Add hook `useForgeInsightsExecutionResult()`:
  - start(jobId, workspaceId)
  - status: idle|running|success|failed|timeout
  - result/error
- Integrate into existing `useForgeInsightsChatThread` send flow.
- Keep all API calls typed and workspace-scoped headers enforced.

Tests:
- chat response with mode=education_pipeline starts polling.
- succeeded execution appends assistant_message markdown bubble.
- failed execution appends error bubble.
- timeout shows retry action.
```

