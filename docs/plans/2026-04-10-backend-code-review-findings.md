# Backend Code Review Findings

Date: 2026-04-10
Scope: `query-forge-api/`

## Review Basis

- Static review of current backend Python sources
- Targeted repo scans for oversized modules, ignored parameters, stale compatibility surfaces, and runtime warnings
- `ruff check query-forge-api/app --select ARG001,ARG002,F841`
- Focused inspection of high-signal modules under `app/factory.py`, `app/config`, `app/services`, and `app/infra`

## Priority Findings

### P1: Request audit logging can still persist secrets

Evidence:

- [factory.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/factory.py#L61) only masks top-level `password` and `token` keys.
- [factory.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/factory.py#L172) stores that masked payload in `g.audit_data["request_body"]`.
- [factory.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/factory.py#L189) pushes the full audit record into Valkey.

Risk:

- Request bodies for destinations, datasource credentials, webhook delivery, API keys, client secrets, refresh tokens, and nested secrets can still be stored in the audit queue.
- The masking is shallow and key-name specific, so structurally different secret payloads are not protected.

Recommended change:

- Centralize recursive secret scrubbing for request logging.
- Default to an allowlist or a denylist that includes `api_key`, `secret`, `client_secret`, `refresh_token`, `webhook_url`, `password`, and nested variants.
- Add regression tests for nested and non-password secret payloads.

### P1: SMTP port reads the wrong environment variable

Evidence:

- [__init__.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/config/__init__.py#L68) uses `os.getenv("SMPT_PORT")` instead of `SMTP_PORT`.

Risk:

- Normal deployments that set `SMTP_PORT` are silently ignored and fall back to the default path in app initialization.
- Mail behavior can drift between environments without an obvious error.

Recommended change:

- Fix the environment variable name.
- Add a config test that proves `SMTP_PORT` is honored.

### P1: Broker health can report `ok` even when no Celery workers are reachable

Evidence:

- [health_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/admin/health_service.py#L140) records `worker_ping_ok`.
- [health_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/admin/health_service.py#L149) computes `ok` using only Valkey ping and broker connection, not worker availability.

Risk:

- The admin health endpoint can show a healthy broker while all workers are down.
- Async-heavy features can appear healthy to operators even though jobs will never execute.

Recommended change:

- Decide whether worker presence is required for `ok`.
- If workers are optional in some environments, expose a distinct degraded state instead of green.
- Add a test that covers broker-up / worker-down behavior explicitly.

### P2: Workspace inventory freshness controls are dead, so reads can trigger unnecessary sync work

Evidence:

- [domain_table_read_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/domain_table_read_service.py#L105) accepts `min_fresh_age_minutes`.
- [domain_table_read_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/domain_table_read_service.py#L110) always attempts registry sync when `ensure_snapshot=True` and `schema` is present, without checking freshness.

Risk:

- Callers may assume there is a freshness gate, but schema-filtered table reads can still trigger inventory refresh every time.
- This adds unnecessary metadata-provider load and request latency.

Recommended change:

- Either honor `min_fresh_age_minutes` against `workspace_table.last_seen_at` or remove the parameter from the contract.
- Add tests that cover “fresh enough: skip sync” and “stale: sync”.

### P2: Planner policy scoping is only partially implemented

Evidence:

- [planner_projection_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_projection_policy_service.py#L233) accepts `vertical_norm` and `base_domain_id`.
- [planner_projection_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_projection_policy_service.py#L262) only filters by `workspace_id`.
- [planner_projection_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_projection_policy_service.py#L337) returns `vertical_norm` and `base_domain_id` as if they shaped the result.
- [planner_projection_policy.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/models/domain/planner_projection_policy.py#L143) exposes both `scope_vertical_norm` and `scope_base_domain_id` on the upsert schema and model.
- [planner_domain_selection_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_domain_selection_policy_service.py#L399) hardcodes `scope_vertical_norm` to `None` on write.
- [planner_prompt_intent_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_prompt_intent_policy_service.py#L539) hardcodes `scope_vertical_norm` to `None` on write.

Risk:

- Vertical- or domain-scoped policy behavior is not trustworthy.
- The API and database schema both advertise scoping that the service layer either ignores or strips out.

Recommended change:

- Either fully implement vertical/base-domain scoping in read and write paths, or remove the scope fields from the public contract until they are supported.
- Add round-trip tests proving scoped policies persist and affect lookup.

### P2: Policy write/delete surfaces accept `actor_user_id` and then discard it

Evidence:

- [planner_domain_selection_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_domain_selection_policy_service.py#L385) accepts `actor_user_id`, then [planner_domain_selection_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_domain_selection_policy_service.py#L388) deletes it.
- [planner_domain_selection_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_domain_selection_policy_service.py#L509) does the same on delete.
- [planner_prompt_intent_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_prompt_intent_policy_service.py#L525) accepts `actor_user_id`, then [planner_prompt_intent_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_prompt_intent_policy_service.py#L528) deletes it.
- [planner_prompt_intent_policy_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/planner_prompt_intent_policy_service.py#L649) does the same on delete.

Risk:

- Admin-write contracts imply auditability that does not exist.
- If policy edits need attribution later, the service layer is already discarding the necessary context.

Recommended change:

- Persist actor metadata in audit/event tables or explicitly remove the argument from the service contract.
- Add tests that verify actor attribution if the field stays.

### P2: The analytics executor adapter silently ignores execution-context parameters

Evidence:

- [executor_adapter.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/analytics/executor_adapter.py#L37) accepts `warehouse_id`, `wait`, `qf_timeout_s`, and `qf_result_fmt`, then [executor_adapter.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/analytics/executor_adapter.py#L43) discards them.
- [executor_adapter.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/analytics/executor_adapter.py#L52) accepts `warehouse_id`, `catalog`, `schema`, and `qf_result_fmt`, then [executor_adapter.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/analytics/executor_adapter.py#L57) discards them.

Risk:

- Callers can believe statement execution is honoring per-call warehouse/catalog/schema settings when it is not.
- Misconfiguration becomes silent instead of obvious.

Recommended change:

- Either implement context application for compatible executors or reject unsupported parameters explicitly.
- Add contract tests around non-Databricks execution so context loss is visible.

### P2: Domain vector indexing advertises vertical scoping but ignores it

Evidence:

- [domain_index_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/vector/domain_index_service.py#L125) accepts `vertical_norm`, then [domain_index_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/vector/domain_index_service.py#L129) discards it.
- [domain_index_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/vector/domain_index_service.py#L152) accepts `vertical_norm`, then [domain_index_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/vector/domain_index_service.py#L154) discards it.
- [domain_index_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/vector/domain_index_service.py#L234) accepts `vertical_norm`, then [domain_index_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/vector/domain_index_service.py#L242) discards it.

Risk:

- Vector search and reindex behavior can mix domains across verticals even when callers request vertical-specific work.
- The API contract is misleading for multi-vertical tenants.

Recommended change:

- Either filter/index by vertical consistently or remove the parameter from the API until it is real.
- Add tests that prove vertical isolation.

### P2: Minimal chat fallback storage ignores TTL and can grow without bound

Evidence:

- [minimal_chat_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/chat/minimal_chat_service.py#L365) calculates `_conversation_ttl_seconds`.
- [minimal_chat_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/chat/minimal_chat_service.py#L311) receives `qf_ttl_seconds`.
- [minimal_chat_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/chat/minimal_chat_service.py#L319) writes directly into `_IN_MEMORY_CONV_STORE` with no expiry metadata.
- [minimal_chat_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/chat/minimal_chat_service.py#L295) lists all matching in-memory keys forever if Valkey is unavailable.

Risk:

- A Valkey outage can turn the in-memory fallback into an unbounded conversation cache.
- Expiry semantics differ between normal and degraded modes.

Recommended change:

- Track expiry alongside in-memory values and evict on read/list.
- Consider bounding the fallback store and documenting the degraded-mode behavior.

### P3: Several compatibility surfaces are now dead code but still shape the public contract

Evidence:

- [metadata/gateway.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/metadata/gateway.py#L16) accepts `mode` and `legacy_repo`, then [metadata/gateway.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/metadata/gateway.py#L21) discards them.
- [metadata/gateway.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/metadata/gateway.py#L25) and [metadata/gateway.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/metadata/gateway.py#L29) always report `"workspace"`.
- [domain_table_read_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/domain_table_read_service.py#L26) still accepts `metadata_mode`, then [domain_table_read_service.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/domain/domain_table_read_service.py#L27) discards it.
- [forge_insights_conversation_store.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/chat/forge_insights_conversation_store.py#L45) and [forge_insights_conversation_store.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/chat/forge_insights_conversation_store.py#L130) still accept TTL but immediately discard it.

Risk:

- New callers get a misleading picture of what the backend supports.
- Tests and adapters can keep reinforcing obsolete contracts.

Recommended change:

- Remove dead compatibility parameters or replace them with explicit `NotImplementedError` / validation errors.
- Collapse “legacy” shims once the migration is complete.

### P3: UTC timestamp helper is already on a deprecated path

Evidence:

- [execution_status_helpers.py](/Users/mmaslak/Local%20Documents/projects/query_forge/query-forge-api/app/services/execution/execution_status_helpers.py#L7) uses `datetime.utcnow()`.
- Full pytest currently emits the deprecation warning from that helper.

Risk:

- The warning is already visible in the backend test suite.
- This will eventually become a Python upgrade problem.

Recommended change:

- Switch to timezone-aware UTC timestamps with `datetime.now(datetime.UTC)`.

## Workstreams To Turn Into a Plan

1. Security and operational correctness
   - Fix request-body secret scrubbing.
   - Fix the `SMTP_PORT` env bug.
   - Tighten broker health semantics so worker outages are visible.

2. Contract honesty and parameter cleanup
   - Remove or implement ignored parameters such as `metadata_mode`, `mode`, `legacy_repo`, `warehouse_id`, `catalog`, `schema`, and TTL fields.
   - Add tests that fail if these arguments are silently ignored again.

3. Planner policy scoping and auditability
   - Make vertical/base-domain scoping real end-to-end or remove it from the contract.
   - Decide whether `actor_user_id` should drive audit storage; if yes, implement it consistently.

4. Caching and degraded-mode behavior
   - Put bounded TTL behavior on the in-memory chat fallback.
   - Review other degraded-mode stores for contract drift versus primary storage.

5. Runtime hygiene
   - Remove visible deprecation warnings like `utcnow()`.
   - Follow up on the broader unused-argument sweep, which currently reports 41 stale parameters in backend app code.

## Commands Used

```bash
ruff check query-forge-api/app --select ARG001,ARG002,F841 --output-format concise
ruff check query-forge-api/app --select B018,PLC0415,TRY400 --output-format concise
```
