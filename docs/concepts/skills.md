# Skills

## What it is

Skills are reusable automation blocks that run against saved queries. Each skill has a type, a configuration, and an optional schedule. When a skill executes, it re-runs its associated saved query and applies its logic (alert, digest, freshness check, delivery).

## Why it matters

Skills turn QueryForge from a query-on-demand tool into an automated monitoring and reporting platform. Instead of manually checking a query every week, a user sets up a skill that does it automatically and delivers results to email or a webhook.

## Who uses it

- **Skills users** — create and manage their own skills (`skills:user` role + skill ownership).
- **Skills admins** — can manage all skills in a workspace, manage destinations, and configure schedules.

## Key concepts

### Skill Types (CODE_CONFIRMED from `app/skills/`)

| Type | Description |
|------|-------------|
| `threshold_alert` | Fires when a numeric result crosses a configured threshold. Supports operators and severity levels. |
| `ai_summary_digest` | Calls the configured summarizer LLM to generate a narrative summary of query results. Supports comparison with a previous snapshot. |
| `data_freshness_check` | Verifies that data was last updated within a configured staleness window. |
| `email_delivery` | Delivers results or a digest via email using configured SMTP/SES. |
| `webhook_delivery` | POSTs results payload to a configured webhook URL. |

### Skill Registry
`SkillRegistry` (`app/skills/registry.py`) is an auto-discovery registry. Skills register themselves via `@SkillRegistry.register`. The runner looks up skill class by `skill_type`.

### SkillContext and SkillResult
`SkillContext` carries workspace_id, skill_id, config, query results (rows/columns), metadata, and execution context. `SkillResult` (a dict subclass) carries `success`, `message`, `data`, and `error`.

### Schedules
Skills can be attached to cron schedules. Routes:
- `POST /api/v1/skills/{skill_id}/schedules` — create schedule
- `PUT /api/v1/skills/schedules/{schedule_id}` — update schedule
- `GET /api/v1/skills/schedules` — list all workspace schedules
- `GET /api/v1/skills/{skill_id}/schedule/upcoming` — preview upcoming run times
- `POST /api/v1/skills/schedule/validate` — validate a cron expression
- `GET /api/v1/skills/scheduler/status` — check Celery scheduler status

### Execution
- `POST /api/v1/skills/{skill_id}/execute` — trigger immediate execution
- `GET /api/v1/skills/{skill_id}/executions` — list past executions (alias: `/runs`)
- `POST /api/v1/skills/{skill_id}/acknowledge` — acknowledge/clear an alert state

### Destinations
Delivery destinations (email accounts, webhook endpoints) used by delivery skills.
- `GET /api/v1/destinations/types` — list available destination types
- `GET/POST /api/v1/destinations/` — list/create destinations
- `GET/PUT/DELETE /api/v1/destinations/{destination_id}` — manage a destination
- `POST /api/v1/destinations/{destination_id}/test` — test a destination connection

### Async Execution
Skill execution is handled by Celery tasks in `app/tasks/skill_runner.py`. The `execute_skill` task fetches the skill record, resolves its type, builds context, and dispatches to the registered skill class.

### Ownership
Skills use ownership-based access: a skill owner can manage their own skill; non-owners need `skills:admin` to access others' skills. Enforced via `@require_ownership("QuerySkill", ...)` decorator (CODE_CONFIRMED from backend-audit Task 6).

## Related features

- [Saved Queries](saved-queries.md)
- [Agents](agents.md)
- [User Guide: Skills](../user-guides/agents-overview.md)
- [Spec: Skills v7 (Inline AI Analysis)](../../specs/SKILLS_SPEC_v7.md)

## Source grounding
- STATUS: CODE_CONFIRMED
- Sources:
  - `app/skills/base.py`
  - `app/skills/registry.py`
  - `app/skills/threshold_alert.py`, `app/skills/ai_summary_digest.py`, `app/skills/data_freshness_check.py`, `app/skills/webhook_delivery.py`, `app/skills/email_delivery.py`
  - `app/routes/skills_routes.py`
  - `app/routes/destination_routes.py`
  - `app/tasks/skill_runner.py`
  - `.claude/audits/backend-audit.md` (Task 6)
