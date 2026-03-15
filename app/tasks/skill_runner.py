from __future__ import annotations

import json as _json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.celery_app import celery

logger = logging.getLogger(__name__)

_SKILL_EXECUTE_ROW_CAP = 500


@celery.task(name="qf.skills.execute")
def execute_skill_task(
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


@celery.task(name="qf.skills.dispatch_due")
def dispatch_due_skills_task() -> Dict[str, Any]:
    from app import create_app

    app = create_app()
    with app.app_context():
        return _run_dispatch_due()


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
        config = skill_row.get("config_json") or {}
        if isinstance(config, str):
            config = _json.loads(config)

        rows: List[Dict[str, Any]] = []
        columns: List[Any] = []
        if query_id:
            rows, columns = _execute_skill_query(workspace_id=workspace_id, query_id=str(query_id))

        frontend_base_url = current_app.config.get("FRONTEND_BASE_URL", "http://localhost:3000")

        from app.skills.base import SkillContext
        from app.skills.registry import SkillRegistry

        context = SkillContext(
            workspace_id=workspace_id,
            skill_id=skill_id,
            execution_id=execution_id,
            config=config,
            frontend_base_url=frontend_base_url,
            rows=rows,
            columns=columns,
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
        logger.exception("execute_skill_task failed skill_id=%s execution_id=%s", skill_id, execution_id)
        sql.execute_write(
            "UPDATE skill_executions SET status = 'failed', completed_at = :now, error_message = :err WHERE id = :id",
            {"now": datetime.now(timezone.utc), "id": execution_id, "err": str(exc)[:2000]},
        )
        raise


def _execute_skill_query(*, workspace_id: str, query_id: str):
    from app.adapters.mysql_sql_executor import ForgeMetaSQL
    from app.services.domain_resolver import DomainResolver
    from app.services.query_forge_service import QueryForgeService
    from app.services.workspace_inventory.workspace_context import WorkspaceContextBuilder

    sql = ForgeMetaSQL()
    rows_q = sql.execute_query_mappings(
        "SELECT sql_json FROM saved_query WHERE id = :id AND workspace_id = :ws AND is_deleted = 0 LIMIT 1",
        {"id": query_id, "ws": workspace_id},
    )
    if not rows_q:
        logger.warning("_execute_skill_query: saved_query %s not found in workspace %s", query_id, workspace_id)
        return [], []

    raw = rows_q[0]["sql_json"]
    sql_json: Dict[str, Any] = _json.loads(raw) if isinstance(raw, str) else (raw or {})

    ctx = WorkspaceContextBuilder().build(workspace_id)
    svc = QueryForgeService(
        executor=ctx.sql_exec,
        domain_resolver=DomainResolver(workspace_id=workspace_id),
    )
    result = svc.run(raw_query=sql_json, mode="export", limit=_SKILL_EXECUTE_ROW_CAP, offset=0)
    return result.rows or [], result.columns or []


def _run_dispatch_due() -> Dict[str, Any]:
    from app.adapters.mysql_sql_executor import ForgeMetaSQL

    sql = ForgeMetaSQL()
    now = datetime.now(timezone.utc)

    due_rows = sql.execute_query_mappings(
        """
        SELECT ss.id AS schedule_id, ss.skill_id, ss.workspace_id
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
    for row in due_rows:
        skill_id = str(row["skill_id"])
        workspace_id = str(row["workspace_id"])
        schedule_id = str(row["schedule_id"])
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
            sql.execute_write(
                "UPDATE skill_schedules SET last_run_at = :now, next_run_at = NULL WHERE id = :id",
                {"now": now, "id": schedule_id},
            )
            execute_skill_task.apply_async(
                kwargs={
                    "skill_id": skill_id,
                    "workspace_id": workspace_id,
                    "execution_id": execution_id,
                    "triggered_by": "schedule",
                }
            )
            dispatched.append({"skill_id": skill_id, "execution_id": execution_id})
        except Exception:
            logger.exception("dispatch_due: failed to dispatch skill_id=%s schedule_id=%s", skill_id, schedule_id)

    return {"dispatched": len(dispatched), "items": dispatched}


__all__ = ["execute_skill_task", "dispatch_due_skills_task"]
