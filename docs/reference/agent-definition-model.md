# Reference: Agent Definition Model

## Purpose

Describes the data model for Agent definitions as specified in the Agent Layer design. NOTE: implementation is NEEDS_VERIFICATION.

## Status

NEEDS_VERIFICATION: This reference is based on the spec (`specs/queryforge_agent_layer_codex_spec.md`). No implementation was found during code inventory. Verify actual database schema and API before relying on this reference.

## Agent Definition (per spec)

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Agent identifier |
| `workspace_id` | string | Workspace scope |
| `name` | string | Human-readable name |
| `goal` | string | Goal description (e.g., "Monitor attendance health") |
| `skills` | list | Ordered list of skill compositions |
| `decision_config` | object | Conditional logic configuration |
| `schedule` | string/null | Cron expression for scheduled runs |
| `is_active` | bool | Whether agent is enabled |
| `created_by` | string | Creator user ID |
| `created_at` | datetime | Creation timestamp |
| `updated_at` | datetime | Last update timestamp |

## Agent State (per spec)

| Field | Type | Description |
|-------|------|-------------|
| `agent_id` | string | Agent reference |
| `last_run` | datetime | Last execution timestamp |
| `last_result_snapshot` | object | Snapshot of last query results |
| `prior_highlights` | list | AI-generated highlights from prior run |
| `prior_alert_state` | string | Last alert state |
| `change_detection_history` | list | History of material change detections |

## Skill Composition (per spec)

Each skill in the agent's composition:

| Field | Type | Description |
|-------|------|-------------|
| `skill_id` | string | Reference to an existing skill |
| `skill_type` | string | Type identifier |
| `order` | int | Execution order |
| `condition` | object/null | Condition that must be true to execute this step |
| `config_override` | object/null | Per-run config overrides |

## Decision Config (per spec)

| Field | Type | Description |
|-------|------|-------------|
| `notify_on_threshold` | bool | Notify if threshold condition met |
| `notify_on_material_change` | bool | Notify if results changed materially |
| `notify_on_freshness_failure` | bool | Notify if data is stale |
| `material_change_threshold_pct` | float | What counts as a material change |

## Allowed values

Skill types available for agent composition: `threshold_alert`, `ai_summary_digest`, `data_freshness_check`, `email_delivery`, `webhook_delivery`.

## Source grounding
- STATUS: SPEC_CONFIRMED (design), NEEDS_VERIFICATION (implementation)
- Sources:
  - `specs/queryforge_agent_layer_codex_spec.md`
