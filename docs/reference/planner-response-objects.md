# Reference: Planner Response Objects

## Purpose

Describes the key response types returned by the planner pipeline and query execution system.

## ForgeCompiledQuery

Produced by `QueryForgeService.compile()`.

| Field | Type | Description |
|-------|------|-------------|
| `sql` | string | Compiled SQL query (parameterized) |
| `qf_count_sql` | string | SQL for total count query |
| `params` | dict | Query parameters |
| `qf_output_cols` | list[dict] | Column metadata for the output |

## QueryForgeRunResult

Produced by `QueryForgeService.run()` and returned by execution endpoints.

| Field | Type | Description |
|-------|------|-------------|
| `sql` | string | Original SQL (parameterized) |
| `qf_rendered_sql` | string | SQL with parameters rendered in |
| `params` | dict | Query parameters |
| `rows` | list | Result rows |
| `columns` | list[dict] | Column metadata |
| `total` | int | Total row count (for pagination) |
| `limit` | int | Page size used |
| `offset` | int | Page offset used |

## Plan response (planner_domain)

NEEDS_VERIFICATION: The exact top-level plan response shape is not confirmed from code inspection. The following is inferred from service structure and spec references.

The planner `POST` endpoint returns an object containing:

| Field | Type | Description |
|-------|------|-------------|
| `plan` | object | The SQL-JSON v2 plan (structured query) |
| `sql` | string | Compiled SQL |
| `explanation` | object/string | Human-readable explanation of the plan |
| `next_actions` | list | Suggested follow-up queries (if enabled) |
| `conversation_id` | string | For multi-turn conversation continuity |
| `domain` | object | Selected domain metadata |
| `debug` | object | Pipeline trace reference (if tracing enabled) |
| `norm_debug` | object | Normalization debug info |

## Plan v2 schema

The LLM produces a "schema v2" JSON object. Its full schema is defined in `app/services/planner_domain/schema_v2.py` and `app/services/planner_domain/validate_v2.py`. NEEDS_VERIFICATION: reading these files would be needed for a complete reference.

## Execution status

`GET /api/v1/executions/{job_id}/status` response:

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `queued\|running\|success\|failed\|canceled` |
| `job_id` | string | Job identifier |

NEEDS_VERIFICATION: exact fields.

## ForgeMatch run status

`GET /api/v1/forge-match/status/{job_id}` response (CODE_CONFIRMED from frontend README):

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `queued\|analyzing\|analyzed\|failed\|canceled` |
| `current_phase` | string | Current pipeline phase |
| `current_source_row_id` | string | Row being processed |
| `source_total` | int | Total source fields |
| `source_done` | int | Processed count |
| `source_skipped` | int | Skipped count |
| `source_failed` | int | Failed count |
| `progress_pct` | float | 0-100 progress |
| `analysis_error` | string/null | Error message if failed |

## SkillResult

Returned by skill execution.

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | Whether execution succeeded |
| `message` | string | Human-readable status message |
| `data` | dict | Output data (skill-specific) |
| `error` | string/null | Error message if failed |

## Source grounding
- STATUS: CODE_CONFIRMED (ForgeCompiledQuery, QueryForgeRunResult, SkillResult), NEEDS_VERIFICATION (plan response shape)
- Sources:
  - `app/services/query_forge_service.py` (dataclass definitions)
  - `app/skills/base.py` (SkillResult)
  - `src/features/forgeMatch/README.md` (ForgeMatch status fields)
