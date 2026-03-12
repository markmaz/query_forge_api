# Workspace LLM Configuration — Implementation Notes

**Date:** 2026-03-11

## Tables Created

- `workspace_llm` — see `migrations/20260311_add_workspace_llm.sql`
  - workspace_id VARCHAR(255) (string FK, matches existing workspace identity)
  - api_key_encrypted TEXT nullable (Fernet-encrypted at rest)
  - role VARCHAR(64) (planner | ner | summarizer | query_generator | enrichment)
  - provider VARCHAR(64) (openai | anthropic | azure_openai | ollama | generic)
  - Unique constraint: enforced in service layer (MySQL partial index limitation)

## Routes Added

```
GET    /api/v1/llm-roles
GET    /api/v1/llm-providers
GET    /api/v1/workspaces/{workspace_id}/llms
POST   /api/v1/workspaces/{workspace_id}/llms
GET    /api/v1/workspaces/{workspace_id}/llms/{llm_id}
PUT    /api/v1/workspaces/{workspace_id}/llms/{llm_id}
DELETE /api/v1/workspaces/{workspace_id}/llms/{llm_id}
POST   /api/v1/workspaces/{workspace_id}/llms/{llm_id}/test
```

## Encryption Approach

Fernet symmetric encryption (cryptography library). Key from `QF_LLM_ENCRYPTION_KEY` env var.
- Raw API key never persisted; always encrypted via `encrypt_api_key()` before DB write
- Never returned in REST responses — only `has_api_key: bool` and `masked_api_key: str | null`
- Decryption happens only in `_to_internal_dict()` for internal pipeline use

## Fallback Behavior

`WorkspaceLLMService.get_llm_for_role()` falls back to env var config when no DB record exists:
- planner/query_generator/enrichment → `VLLM_BASE_URL` + `SEMANTIC_PLAN_LLM_MODEL`
- ner/summarizer → `SEMANTIC_LLM_ENDPOINT` + `SEMANTIC_LLM_MODEL`
- Returns `None` if neither DB nor env is configured

Pipeline integrates via `app.config.llm_resolver.resolve_llm_config(workspace_id, role)`.

## Unique Active LLM Per Role

MySQL partial unique indexes not used. Enforced in `WorkspaceLLMService._assert_no_active_for_role()`.
Service raises `ValueError` if creating/updating would create a second active LLM for same workspace+role.

## Frontend Surfaces

1. **CustomerInitializationPage** — Step 4 (new, optional) with multi-row LLM draft list. Step 5 = old "Bind + Confirm".
2. **WorkspaceLLMPage** — Standalone page at `/admin/tenancy/workspace-llms` under System Admin → Tenancy.

## Deferred Items

- Navigation sidebar link for WorkspaceLLMPage not added (sidebar uses static menuList — add if sidebar is updated)
- `test_connection` uses `httpx` — ensure it's in requirements.txt
- Full E2E Playwright tests deferred
