# Problem: LLM Failure or Unavailability

## Symptoms

- Query Studio returns a 503 error when submitting a prompt
- "No LLM configured" message appears
- AI analysis returns an error
- ForgeInsights chat does not respond
- Skill execution fails with an LLM-related error

## Likely causes

1. **No LLM configured for the workspace role** — neither a workspace LLM record nor the relevant env var is set
2. **LLM API key is invalid or expired** — the workspace LLM record has a bad API key
3. **LLM endpoint is unreachable** — network issue or the endpoint URL is wrong
4. **LLM rate limited** — the API key has hit usage limits
5. **Model name mismatch** — the configured model name doesn't exist at the endpoint

## How to confirm

1. Check workspace LLM configuration: `GET /api/v1/workspaces/{workspace_id}/llms`. Is there an active LLM for the required role?
2. Test the LLM connection: `POST /api/v1/workspaces/{workspace_id}/llms/{llm_id}/test`. This verifies the endpoint is reachable and the key is valid.
3. Check the application log file (configured via `LOG_FILE` env var). Look for `LLMClient` or `WorkspaceLLMService` error entries.
4. Check which roles are needed:
   - Query Studio prompt planning → `planner` role
   - AI inline analysis → `summarizer` role
   - ForgeInsights chat → (NEEDS_VERIFICATION: which role)
   - ForgeMatch LLM ranking → `planner` role or `llm_id` override

## How to fix

### Fix 1: Add a workspace LLM for the missing role
`POST /api/v1/workspaces/{workspace_id}/llms` with the correct `role`, `provider`, `base_url`, and `api_key`.

Supported providers: `openai`, `anthropic`, `azure_openai`, `ollama`, `generic`.
Roles: `planner`, `ner`, `summarizer`, `query_generator`, `enrichment`.

### Fix 2: Set environment variable fallback
If workspace LLM management is not yet configured, set env vars:
- For planner: `VLLM_BASE_URL` + `SEMANTIC_PLAN_LLM_MODEL`
- For ner/summarizer: `SEMANTIC_LLM_ENDPOINT` + `SEMANTIC_LLM_MODEL`

### Fix 3: Rotate the API key
If the key is invalid: `PUT /api/v1/workspaces/{workspace_id}/llms/{llm_id}` with the new key. The key is Fernet-encrypted at rest — only `has_api_key: bool` is shown in responses.

### Fix 4: Check LLM endpoint / data environment
If using a locally hosted LLM: `GET /api/v1/data-environment/llm/status`. Restart if needed via `POST /api/v1/data-environment/llm/start`.

## Related docs

- [Admin: Deployment Overview](../admin/deployment-overview.md)
- [Concepts: Workspaces and Organizations](../concepts/workspaces-and-organizations.md)
- [Implementation Notes: Workspace LLM](../../.claude/audits/implementation-notes.md)

## Source grounding
- STATUS: CODE_CONFIRMED
- Sources:
  - `.claude/audits/implementation-notes.md`
  - `app/routes/data_environment.py`
  - `app/services/llm/` (inferred existence)
