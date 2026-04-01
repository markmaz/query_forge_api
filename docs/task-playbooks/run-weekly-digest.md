# Goal: Set Up a Weekly AI Digest

## Audience

Users who want automated weekly AI-generated summaries of a saved query delivered via email or webhook.

## What you need

- A saved query (see [Save and Share a Query](save-and-share-query.md))
- `skills:user` role (or `workspace_admin`)
- `skills` feature enabled in the workspace
- A delivery destination configured (email address or webhook URL)
- The `summarizer` LLM role configured for the workspace (or env-var fallback)

## Steps

1. **Configure a delivery destination**
   `POST /api/v1/destinations/` — create a destination record. Destination types: email, webhook (exact types from `GET /api/v1/destinations/types`). Test the destination with `POST /api/v1/destinations/{destination_id}/test`.

2. **Create the skill**
   `POST /api/v1/skills/` — create a new skill with:
   - `name`: a descriptive name
   - `skill_type`: `ai_summary_digest`
   - `query_id`: the ID of your saved query
   - `config`: configuration for the digest (prompt hint, include_comparison flag)

3. **Attach an email delivery action (optional)**
   If you want delivery via email, create a second skill of type `email_delivery` referencing the same query, or configure delivery within the digest skill config (NEEDS_VERIFICATION: exact config schema for chaining delivery).

4. **Create a weekly schedule**
   `POST /api/v1/skills/{skill_id}/schedules` — provide a cron expression for weekly execution. Example: `0 8 * * 1` (every Monday at 8am). Validate the expression first with `POST /api/v1/skills/schedule/validate`.

5. **Preview upcoming runs**
   `GET /api/v1/skills/{skill_id}/schedule/upcoming` — confirm the schedule will fire when expected.

6. **Verify scheduler is running**
   `GET /api/v1/skills/scheduler/status` — confirms the Celery beat scheduler is active.

7. **Run a manual test**
   `POST /api/v1/skills/{skill_id}/execute` — trigger an immediate execution to verify the LLM summary is generated and delivered correctly.

8. **Review execution history**
   `GET /api/v1/skills/{skill_id}/executions` — view past runs with status and output.

## What happens next

Every week the Celery scheduler fires the skill, re-executes the saved query, generates an AI narrative, and delivers it to the configured destination.

## Common issues

- **503 on execute** — no LLM configured for `summarizer` role. Add workspace LLM or set `SEMANTIC_LLM_ENDPOINT` env var.
- **Scheduler not firing** — check `GET /api/v1/skills/scheduler/status`. Celery beat may not be running.
- **Delivery failing** — test the destination via `POST /api/v1/destinations/{destination_id}/test`.

## Related docs

- [Concepts: Skills](../concepts/skills.md)
- [Troubleshoot: Agent/Skill Execution](../troubleshooting/agent-execution-issue.md)
- [Troubleshoot: LLM Failure](../troubleshooting/llm-failure.md)

## Source grounding
- STATUS: CODE_CONFIRMED (routes), NEEDS_VERIFICATION (exact config schema for ai_summary_digest)
- Sources:
  - `app/routes/skills_routes.py`
  - `app/routes/destination_routes.py`
  - `app/skills/ai_summary_digest.py`
  - `app/tasks/skill_runner.py`
