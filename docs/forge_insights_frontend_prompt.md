# ForgeInsights Frontend Implementation Prompt (Conversation ID + Context Memory)

Use this prompt with your frontend coding assistant:

```text
Implement production-ready conversation memory for the ForgeInsights chat UI.

Feature naming:
- Use ForgeInsights naming everywhere (components, hooks, API client names, localStorage keys, analytics events).

Backend endpoints:
- POST /api/v1/chat/forge-insights
- GET /api/v1/chat/forge-insights/conversations?limit=50
- GET /api/v1/chat/forge-insights/conversations/:conversationId
- DELETE /api/v1/chat/forge-insights/conversations/:conversationId

Auth/workspace headers:
- Always send Authorization: Bearer <token>
- Always send X-Workspace-Id: <workspaceId>

POST request body:
- messages: [{ role: "user" | "assistant" | "system", content: string }]
- conversation_id?: string
- temperature?: number
- max_tokens?: number
- debug?: boolean

POST response includes:
- conversation_id (required; persist this)
- message.content

Conversation memory behavior:
1) Persist active conversation_id in localStorage by workspace:
   key: forgeInsights:conversationId:<workspaceId>
2) On send message:
   - read active conversation_id from state/localStorage
   - include it in POST if present
3) On response:
   - store returned conversation_id into state/localStorage
4) If POST returns 404 (conversation expired/not found):
   - clear local conversation_id
   - retry once without conversation_id
5) Keep prior UI messages in state so each new user prompt builds on the current thread naturally.

Conversation history UI:
- Build a left sidebar list from GET /conversations.
- Show: title, updated_at, message_count.
- Clicking a row loads GET /conversations/:conversationId and hydrates the message thread.
- “New chat” clears active conversation_id + starts empty thread.
- “Delete chat” calls DELETE endpoint, removes row from sidebar, and clears state if it was active.

TypeScript contracts:
- Create types:
  - ForgeInsightsChatMessage
  - ForgeInsightsChatRequest
  - ForgeInsightsChatResponse
  - ForgeInsightsConversationListItem
  - ForgeInsightsConversationDetail

Implementation shape:
- Create `useForgeInsightsChat(workspaceId)` hook that owns:
  - messages
  - activeConversationId
  - conversations list
  - sendMessage(text)
  - loadConversation(conversationId)
  - newConversation()
  - deleteConversation(conversationId)
  - loading/error states

Quality requirements:
- Strict null/type guards around conversation_id.
- Prevent duplicate send while request is in flight.
- Optimistic append of user message, then append assistant response.
- Surface backend errors in a non-blocking toast/banner.
- Unit-test hook behavior for:
  - initial send (no conversation_id)
  - follow-up send (with conversation_id)
  - 404 retry path
  - localStorage rehydration
```

