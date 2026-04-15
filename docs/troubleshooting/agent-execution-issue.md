# Problem: Skill or Agent Execution Issue

## Symptoms

- Skill execution returns an error
- Scheduled skill did not fire at the expected time
- Execution status shows `failed`
- Execution history shows no recent runs despite a configured schedule
- ForgeMatch analysis gets stuck in `queued` or `analyzing` state

## Likely causes

1. **Celery worker not running** — async tasks cannot execute without a worker
2. **Celery beat not running** — scheduled (cron) tasks won't fire without the beat scheduler
3. **Redis/Valkey connection issue** — broker unavailable
4. **Query execution failure** — the underlying query failed (datasource issue)
5. **LLM failure** — `ai_summary_digest` or inline analysis relies on an LLM (see [LLM Failure](llm-failure.md))
6. **Skill configuration error** — `config_json` has invalid settings
7. **Unknown skill type** — the skill record's `skill_type` is not registered in `SkillRegistry`

## How to confirm

1. **Check broker health**: `GET /api/v1/admin/health/broker` — shows `ok`, `valkey.ping_ok`, `celery.broker_connect_ok`, `celery.worker_ping_ok`, and active workers.

2. **Check scheduler status**: `GET /api/v1/skills/scheduler/status` — confirms Celery beat is running.

3. **View execution history**: `GET /api/v1/skills/{skill_id}/executions` — see recent runs and their error messages.

4. **Check application logs**: Look in the log file (configured via `LOG_FILE` env var) for Celery task errors.

5. **Manual test**: `POST /api/v1/skills/{skill_id}/execute` — runs the skill immediately. If this fails synchronously, the error response includes the failure reason.

## How to fix

### Fix 1: Start Celery worker
```bash
celery -A app.celery_app worker --loglevel=INFO
```

### Fix 2: Start Celery beat (for scheduled tasks)
```bash
celery -A app.celery_app beat --loglevel=INFO
```
(Or configure systemd unit — see `docs/systemd/`.)

### Fix 3: Check Redis/Valkey
Verify the Redis/Valkey service is running and the `CELERY_BROKER_URL` env var is correct.

### Fix 4: Fix the skill configuration
`PATCH /api/v1/skills/{skill_id}` — update the config to correct invalid settings.

### Fix 5: Verify skill type
`GET /api/v1/skills/{skill_id}` — check the `skill_type` value. Valid types are: `threshold_alert`, `ai_summary_digest`, `data_freshness_check`, `email_delivery`, `webhook_delivery`.

### Fix 6: For LLM-dependent skills
See [Troubleshoot: LLM Failure](llm-failure.md).

## Related docs

- [Concepts: Skills](../concepts/skills.md)
- [Admin: Deployment Overview](../admin/deployment-overview.md)
- [Troubleshoot: LLM Failure](llm-failure.md)

## Source grounding
- STATUS: CODE_CONFIRMED
- Sources:
  - `app/routes/skills_routes.py` (SchedulerStatus, SkillExecutionList)
  - `app/routes/admin_routes.py` (BrokerHealth)
  - `app/tasks/skill_runner.py`
  - `app/skills/registry.py`
