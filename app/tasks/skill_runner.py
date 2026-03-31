"""
app/tasks/skill_runner.py

Celery tasks for the QueryForge skills system.

Changes from v2:
  - dispatch_due_skills now records a heartbeat to Valkey on every tick
  - catch_up=False (default) skips overdue runs older than one interval
  - Task names use qf.* prefix to match this project's convention
  - App context acquired via pattern from forge_match_tasks.py

Startup commands:
  Development:
    celery -A app.celery_app worker --loglevel=info
    celery -A app.celery_app beat --loglevel=info      <- must run separately

  Production (systemd):
    Add two systemd units — see docs/systemd/
    queryforge-celery-worker.service
    queryforge-celery-beat.service                     <- Beat MUST be its own unit
"""

from __future__ import annotations

import json as _json
import logging
import uuid
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Dict, List, Optional

from app.celery_app import celery

logger = logging.getLogger(__name__)

_SKILL_EXECUTE_ROW_CAP = 500
_SKILL_META_KEY = "_qf_skill"


# ---------------------------------------------------------------------------
# Core execution task
# ---------------------------------------------------------------------------


@celery.task(name="qf.skills.execute")
def execute_skill(
    *,
    skill_id: str,
    workspace_id: str,
    execution_id: str,
    triggered_by: Optional[str] = None,
) -> Dict[str, Any]:
    from app import create_app

    app = create_app()
    with app.app_context():
        return _run_execute(
            skill_id=skill_id,
            workspace_id=workspace_id,
            execution_id=execution_id,
            triggered_by=triggered_by,
        )


# ---------------------------------------------------------------------------
# Scheduler dispatcher — runs every 60s via Celery Beat
# ---------------------------------------------------------------------------


@celery.task(name="qf.skills.dispatch_due")
def dispatch_due_skills() -> Dict[str, Any]:
    from app import create_app

    app = create_app()
    with app.app_context():
        return _run_dispatch_due()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _run_execute(
    *,
    skill_id: str,
    workspace_id: str,
    execution_id: str,
    triggered_by: Optional[str],
) -> Dict[str, Any]:
    from app.adapters.mysql_sql_executor import ForgeMetaSQL
    from flask import current_app

    sql = ForgeMetaSQL()
    now = datetime.now(timezone.utc)

    sql.execute_write(
        "UPDATE skill_executions SET status = 'running', started_at = :now WHERE id = :id",
        {"now": now, "id": execution_id},
    )

    try:
        skill_rows = sql.execute_query_mappings(
            """
            SELECT id, workspace_id, name, skill_type, query_id, config_json, is_active
            FROM query_skills
            WHERE id = :id AND workspace_id = :ws AND is_active = 1
            LIMIT 1
            """,
            {"id": skill_id, "ws": workspace_id},
        )
        if not skill_rows:
            raise ValueError(f"Skill {skill_id} not found or inactive in workspace {workspace_id}")

        skill_row = dict(skill_rows[0])
        skill_type = str(skill_row["skill_type"])
        query_id = skill_row.get("query_id")
        config = _extract_runtime_config(skill_row.get("config_json"))

        query_execution = _empty_query_execution(query_id=query_id, query_name=skill_row.get("name"))
        if query_id:
            query_execution = _execute_skill_query(workspace_id=workspace_id, query_id=str(query_id))

        frontend_base_url = current_app.config.get("FRONTEND_BASE_URL", "http://localhost:3000")

        from app.skills.base import QueryMetadata, SkillContext
        from app.skills.registry import SkillRegistry

        metadata = QueryMetadata(
            query_id=query_id,
            query_name=str(query_execution.get("query_name") or skill_row.get("name") or ""),
            column_names=list(query_execution.get("column_names") or []),
            column_types=dict(query_execution.get("column_types") or {}),
            row_count=int(query_execution.get("row_count") or 0),
            execution_time_ms=int(query_execution.get("execution_time_ms") or 0),
            executed_at=query_execution.get("executed_at") or now,
        )
        workspace_config = _get_workspace_config(workspace_id)

        context = SkillContext(
            workspace_id=workspace_id,
            skill_id=skill_id,
            execution_id=execution_id,
            config=config,
            frontend_base_url=frontend_base_url,
            rows=list(query_execution.get("rows") or []),
            columns=list(query_execution.get("column_names") or []),
            query_id=query_id,
            triggered_by=triggered_by,
            results=list(query_execution.get("rows") or []),
            metadata=metadata,
            workspace_config=workspace_config,
        )

        skill_cls = SkillRegistry.get(skill_type)
        if skill_cls is None:
            raise ValueError(f"Unknown skill_type: {skill_type!r}")

        result = skill_cls().execute(context)

        sql.execute_write(
            "UPDATE skill_executions SET status = 'success', completed_at = :now, result_json = :result WHERE id = :id",
            {"now": datetime.now(timezone.utc), "id": execution_id, "result": _json.dumps(result)},
        )
        return result

    except Exception as exc:
        logger.exception("execute_skill failed skill_id=%s execution_id=%s", skill_id, execution_id)
        sql.execute_write(
            "UPDATE skill_executions SET status = 'failed', completed_at = :now, error_message = :err WHERE id = :id",
            {"now": datetime.now(timezone.utc), "id": execution_id, "err": str(exc)[:2000]},
        )
        raise


def _execute_skill_query(*, workspace_id: str, query_id: str) -> Dict[str, Any]:
    """
    Execute the saved query and return the execution bundle needed by skills.
    Seam: ForgeMetaSQL -> saved_query.sql_json -> WorkspaceSqlContextBuilder -> QueryForgeService
    """
    import json
    from app.adapters.mysql_sql_executor import ForgeMetaSQL
    from app.services.domain_resolver import DomainResolver
    from app.services.query_forge_service import QueryForgeService
    from app.services.workspace_inventory.workspace_context import WorkspaceSqlContextBuilder

    sql = ForgeMetaSQL()
    rows_q = sql.execute_query_mappings(
        "SELECT sql_json, title AS name FROM saved_query "
        "WHERE id = :id AND (workspace_id = :ws OR workspace_id IS NULL) "
        "AND is_deleted = 0 LIMIT 1",
        {"id": query_id, "ws": workspace_id},
    )
    if not rows_q:
        logger.warning("_execute_skill_query: saved_query %s not found in workspace %s", query_id, workspace_id)
        return _empty_query_execution(query_id=query_id, query_name=f"Query {query_id}")

    sql_json = rows_q[0]["sql_json"]
    query_name = str(rows_q[0].get("name") or f"Query {query_id}")
    if isinstance(sql_json, str):
        sql_json = json.loads(sql_json)
    sql_json = sql_json or {}

    ctx = WorkspaceSqlContextBuilder().build(workspace_id)
    svc = QueryForgeService(
        executor=ctx.sql_exec,
        domain_resolver=DomainResolver(workspace_id=workspace_id),
    )
    started = perf_counter()
    result = svc.run(raw_query=sql_json, mode="export", limit=_SKILL_EXECUTE_ROW_CAP, offset=0)
    executed_at = datetime.now(timezone.utc)
    execution_time_ms = max(int((perf_counter() - started) * 1000), 0)
    rows = list(result.rows or [])
    columns = list(result.columns or [])

    return {
        "rows": rows,
        "columns": columns,
        "column_names": _column_names(columns),
        "column_types": _column_types(columns, rows),
        "row_count": len(rows),
        "query_name": query_name,
        "execution_time_ms": execution_time_ms,
        "executed_at": executed_at,
    }


def _get_workspace_config(workspace_id: str) -> dict:
    """
    Return workspace config dict for use by skills.
    Seam: WorkspaceLLMService resolves config only.
    """
    try:
        from app.services.tenancy.workspace_llm_service import WorkspaceLLMService
        llm = WorkspaceLLMService().get_llm_for_role(workspace_id, "default")
        return {"llm": llm}
    except Exception as exc:
        logger.warning("Could not load workspace LLM config for %s: %s", workspace_id, exc)
        return {}


def _extract_runtime_config(config_json: Any) -> Dict[str, Any]:
    if isinstance(config_json, str):
        try:
            config_json = _json.loads(config_json)
        except Exception:
            return {}
    if not isinstance(config_json, dict):
        return {}
    return {k: v for k, v in config_json.items() if k != _SKILL_META_KEY}


def _column_name(column: Any) -> str:
    if isinstance(column, dict):
        for key in ("label", "name", "columnName", "alias", "field"):
            value = column.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                nested_name = _column_name(value)
                if nested_name:
                    return nested_name
    if isinstance(column, str):
        return column
    return ""


def _column_names(columns: List[Any]) -> List[str]:
    names = [_column_name(column) for column in columns]
    return [name for name in names if name]


def _type_name(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, (dict, list)):
        return "json"
    return type(value).__name__


def _column_types(columns: List[Any], rows: List[Dict[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for column in columns:
        name = _column_name(column)
        if not name:
            continue
        declared_type = None
        if isinstance(column, dict):
            declared_type = column.get("type") or column.get("dataType") or column.get("datatype")
        if isinstance(declared_type, str) and declared_type.strip():
            out[name] = declared_type.strip()
            continue
        inferred = next((_type_name(row.get(name)) for row in rows if row.get(name) is not None), "unknown")
        out[name] = inferred
    for row in rows:
        for name, value in row.items():
            if name not in out:
                out[name] = _type_name(value)
    return out


def _empty_query_execution(*, query_id: Any, query_name: Any) -> Dict[str, Any]:
    return {
        "rows": [],
        "columns": [],
        "column_names": [],
        "column_types": {},
        "row_count": 0,
        "query_name": str(query_name or (f"Query {query_id}" if query_id else "")),
        "execution_time_ms": 0,
        "executed_at": datetime.now(timezone.utc),
    }


def _run_dispatch_due() -> Dict[str, Any]:
    """
    Poll skill_schedules for rows where next_run_at <= now and is_active=True.
    Dispatches execute_skill for each due schedule, then advances next_run_at.

    Catch-up protection: if catch_up=False (default) and the schedule is more
    than one full interval overdue, skip it and advance to the next future run.
    This prevents alert/email storms after Beat downtime.
    """
    from app.adapters.mysql_sql_executor import ForgeMetaSQL
    from app.skills.schedule_utils import record_dispatch_heartbeat

    # Record heartbeat so /scheduler/status can verify Beat is alive
    record_dispatch_heartbeat()

    sql = ForgeMetaSQL()
    now = datetime.now(timezone.utc)

    due_rows = sql.execute_query_mappings(
        """
        SELECT ss.id AS schedule_id, ss.skill_id, ss.workspace_id,
               ss.cron_expr, ss.timezone, ss.next_run_at, ss.catch_up
        FROM skill_schedules ss
        JOIN query_skills qs ON qs.id = ss.skill_id
        WHERE ss.is_active = 1
          AND ss.next_run_at IS NOT NULL
          AND ss.next_run_at <= :now
          AND qs.is_active = 1
        ORDER BY ss.next_run_at ASC
        LIMIT 100
        """,
        {"now": now},
    )

    dispatched: List[Dict[str, str]] = []
    skipped_catchup: List[str] = []

    for row in due_rows:
        skill_id = str(row["skill_id"])
        workspace_id = str(row["workspace_id"])
        schedule_id = str(row["schedule_id"])
        cron_expr = str(row.get("cron_expr") or "")
        catch_up = bool(row.get("catch_up", 0))
        next_run_at = row.get("next_run_at")

        # Catch-up protection
        timezone_name = str(row.get("timezone") or "UTC").strip() or "UTC"

        if not catch_up and _is_overdue_by_more_than_one_interval(cron_expr, next_run_at, now):
            next_run_at_value = _resolve_next_scheduled_run(
                cron_expr=cron_expr,
                timezone_name=timezone_name,
                from_dt=now,
            )
            logger.info(
                "Skipping overdue schedule_id=%s (catch_up=False) — advancing.",
                schedule_id,
            )
            sql.execute_write(
                "UPDATE skill_schedules SET last_run_at = :now, next_run_at = :next_run_at WHERE id = :id",
                {"now": now, "next_run_at": next_run_at_value, "id": schedule_id},
            )
            skipped_catchup.append(skill_id)
            continue

        execution_id = str(uuid.uuid4())

        try:
            sql.execute_write(
                """
                INSERT INTO skill_executions (id, skill_id, workspace_id, schedule_id, status, triggered_by, created_at)
                VALUES (:id, :skill_id, :workspace_id, :schedule_id, 'queued', 'schedule', CURRENT_TIMESTAMP)
                """,
                {
                    "id": execution_id,
                    "skill_id": skill_id,
                    "workspace_id": workspace_id,
                    "schedule_id": schedule_id,
                },
            )
            next_run_at_value = _resolve_next_scheduled_run(
                cron_expr=cron_expr,
                timezone_name=timezone_name,
                from_dt=next_run_at or now,
            )
            execute_skill.apply_async(
                kwargs={
                    "skill_id": skill_id,
                    "workspace_id": workspace_id,
                    "execution_id": execution_id,
                    "triggered_by": "schedule",
                }
            )
            sql.execute_write(
                "UPDATE skill_schedules SET last_run_at = :now, next_run_at = :next_run_at WHERE id = :id",
                {"now": now, "next_run_at": next_run_at_value, "id": schedule_id},
            )
            dispatched.append({"skill_id": skill_id, "execution_id": execution_id})
            logger.info("Dispatched skill_id=%s (schedule_id=%s)", skill_id, schedule_id)
        except Exception:
            logger.exception("dispatch_due: failed to dispatch skill_id=%s schedule_id=%s", skill_id, schedule_id)

    logger.info(
        "dispatch_due_skills: dispatched=%s skipped_catchup=%s",
        len(dispatched), len(skipped_catchup),
    )
    return {
        "dispatched": len(dispatched),
        "skipped_catchup": len(skipped_catchup),
        "items": dispatched,
    }


def _is_overdue_by_more_than_one_interval(
    cron_expr: str, next_run_at: Any, now: datetime
) -> bool:
    """
    Returns True if next_run_at is more than one full cron interval in the past
    — i.e. we've missed more than one run.
    """
    if not cron_expr or not next_run_at:
        return False
    try:
        from croniter import croniter

        if isinstance(next_run_at, str):
            next_run_at = datetime.fromisoformat(next_run_at)

        cron = croniter(cron_expr, next_run_at)
        one_interval_later = cron.get_next(datetime)
        now_naive = now.replace(tzinfo=None) if now.tzinfo else now
        return now_naive > one_interval_later.replace(tzinfo=None)
    except Exception:
        return False


def _resolve_next_scheduled_run(
    *,
    cron_expr: str,
    timezone_name: str,
    from_dt: Any,
) -> datetime | None:
    from app.skills.schedule_utils import next_n_runs

    base_dt = from_dt
    if isinstance(base_dt, str):
        try:
            base_dt = datetime.fromisoformat(base_dt)
        except Exception:
            base_dt = None
    if base_dt is None:
        base_dt = datetime.now(timezone.utc)

    upcoming = next_n_runs(cron_expr, timezone_name, n=1, from_dt=base_dt)
    if not upcoming:
        return None
    try:
        next_run_at = datetime.fromisoformat(str(upcoming[0]))
    except Exception:
        return None
    if next_run_at.tzinfo is not None:
        next_run_at = next_run_at.astimezone(timezone.utc).replace(tzinfo=None)
    return next_run_at


# Backward-compat aliases — tasks/__init__.py and the skills feature use old names
execute_skill_task = execute_skill
dispatch_due_skills_task = dispatch_due_skills

__all__ = ["execute_skill", "dispatch_due_skills", "execute_skill_task", "dispatch_due_skills_task"]
