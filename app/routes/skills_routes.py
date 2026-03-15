from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from app.skills.schedule_utils import get_scheduler_health, next_n_runs, validate_cron
from typing import Any, Dict

from flask import g, request
from flask_restx import Namespace, fields

from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.routes.forge_resource import ForgeResource
from app.routes.request_helpers import extract_workspace_id, int_arg, require_user_id

logger = logging.getLogger(__name__)

skills_ns = Namespace("skills", description="QueryForge Skills")


def _serialize_row(row: dict) -> dict:
    import json as _json

    out = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif k == "config_json" and isinstance(v, str):
            try:
                out[k] = _json.loads(v)
            except Exception:
                out[k] = v
        else:
            out[k] = v
    return out

_skill_create_model = skills_ns.model(
    "SkillCreate",
    {
        "name": fields.String(required=True),
        "skill_type": fields.String(required=True),
        "query_id": fields.String(required=False),
        "config_json": fields.Raw(required=False),
        "is_active": fields.Integer(required=False, default=1),
    },
)

_skill_update_model = skills_ns.model(
    "SkillUpdate",
    {
        "name": fields.String(required=False),
        "skill_type": fields.String(required=False),
        "query_id": fields.String(required=False),
        "config_json": fields.Raw(required=False),
        "is_active": fields.Integer(required=False),
    },
)

_schedule_create_model = skills_ns.model(
    "SkillScheduleCreate",
    {
        "cron_expr": fields.String(required=True),
        "timezone": fields.String(required=False, default="UTC"),
        "next_run_at": fields.String(required=False),
        "is_active": fields.Integer(required=False, default=1),
    },
)

_schedule_update_model = skills_ns.model(
    "SkillScheduleUpdate",
    {
        "cron_expr": fields.String(required=False),
        "timezone": fields.String(required=False),
        "next_run_at": fields.String(required=False),
        "is_active": fields.Integer(required=False),
    },
)

_execute_response_model = skills_ns.model(
    "SkillExecuteResponse",
    {
        "execution_id": fields.String(required=True),
        "job_id": fields.String(required=True),
        "status": fields.String(required=True),
    },
)


@skills_ns.route("")
class SkillList(ForgeResource):
    @token_required
    @skills_ns.doc(params={"page": "Page number (default 1)", "page_size": "Page size (default 20, max 100)"})
    def get(self):
        try:
            workspace_id = extract_workspace_id()
            page = int_arg("page", 1)
            page_size = min(int_arg("page_size", 20), 100)
            offset = (page - 1) * page_size

            from app.adapters.mysql_sql_executor import ForgeMetaSQL

            sql = ForgeMetaSQL()
            rows = sql.execute_query_mappings(
                """
                SELECT id, workspace_id, name, skill_type, query_id, config_json,
                       is_active, created_by, created_at, updated_at
                FROM query_skills
                WHERE workspace_id = :ws
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """,
                {"ws": workspace_id, "limit": page_size, "offset": offset},
            )
            total_rows = sql.execute_query_mappings(
                "SELECT COUNT(*) AS cnt FROM query_skills WHERE workspace_id = :ws",
                {"ws": workspace_id},
            )
            total = int((total_rows[0]["cnt"] if total_rows else 0) or 0)
            return {
                "data": [_serialize_row(dict(r)) for r in rows],
                "page": page,
                "page_size": page_size,
                "total": total,
            }, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skills list failed")
            return {"error": "skills list failed"}, 500

    @token_required
    @skills_ns.expect(_skill_create_model, validate=False)
    def post(self):
        try:
            workspace_id = extract_workspace_id()
            user_id = require_user_id()
            body: Dict[str, Any] = request.get_json(silent=True) or {}

            name = str(body.get("name") or "").strip()
            skill_type = str(body.get("skill_type") or "").strip()
            if not name:
                raise ForgeError("name is required", status_code=400)
            if not skill_type:
                raise ForgeError("skill_type is required", status_code=400)

            query_id = body.get("query_id") or None
            config_json = body.get("config_json") or body.get("config") or None
            is_active = int(body.get("is_active", 1))
            skill_id = str(uuid.uuid4())

            from app.adapters.mysql_sql_executor import ForgeMetaSQL
            import json as _json

            sql = ForgeMetaSQL()
            config_str = _json.dumps(config_json) if config_json is not None else None
            sql.execute_write(
                """
                INSERT INTO query_skills (id, workspace_id, name, skill_type, query_id, config_json, is_active, created_by, created_at)
                VALUES (:id, :ws, :name, :skill_type, :query_id, :config_json, :is_active, :created_by, :now)
                """,
                {
                    "id": skill_id,
                    "ws": workspace_id,
                    "name": name,
                    "skill_type": skill_type,
                    "query_id": query_id,
                    "config_json": config_str,
                    "is_active": is_active,
                    "created_by": user_id,
                    "now": datetime.now(timezone.utc),
                },
            )
            rows = sql.execute_query_mappings(
                "SELECT id, workspace_id, name, skill_type, query_id, config_json, is_active, created_by, created_at, updated_at FROM query_skills WHERE id = :id",
                {"id": skill_id},
            )
            return {"data": _serialize_row(dict(rows[0])) if rows else {"id": skill_id}}, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skills create failed")
            return {"error": "skills create failed"}, 500


@skills_ns.route("/<string:skill_id>")
class SkillDetail(ForgeResource):
    @token_required
    def get(self, skill_id: str):
        try:
            workspace_id = extract_workspace_id()
            from app.adapters.mysql_sql_executor import ForgeMetaSQL

            sql = ForgeMetaSQL()
            rows = sql.execute_query_mappings(
                """
                SELECT id, workspace_id, name, skill_type, query_id, config_json,
                       is_active, created_by, created_at, updated_at
                FROM query_skills
                WHERE id = :id AND workspace_id = :ws
                LIMIT 1
                """,
                {"id": skill_id, "ws": workspace_id},
            )
            if not rows:
                raise ForgeError(f"Skill {skill_id} not found", status_code=404)
            return {"data": _serialize_row(dict(rows[0]))}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skills get failed skill_id=%s", skill_id)
            return {"error": "skills get failed"}, 500

    @token_required
    @skills_ns.expect(_skill_update_model, validate=False)
    def put(self, skill_id: str):
        try:
            workspace_id = extract_workspace_id()
            body: Dict[str, Any] = request.get_json(silent=True) or {}

            from app.adapters.mysql_sql_executor import ForgeMetaSQL
            import json as _json

            sql = ForgeMetaSQL()
            existing = sql.execute_query_mappings(
                "SELECT id FROM query_skills WHERE id = :id AND workspace_id = :ws LIMIT 1",
                {"id": skill_id, "ws": workspace_id},
            )
            if not existing:
                raise ForgeError(f"Skill {skill_id} not found", status_code=404)

            updates: Dict[str, Any] = {}
            if "name" in body and body["name"] is not None:
                updates["name"] = str(body["name"]).strip()
            if "skill_type" in body and body["skill_type"] is not None:
                updates["skill_type"] = str(body["skill_type"]).strip()
            if "query_id" in body:
                updates["query_id"] = body["query_id"] or None
            if "config_json" in body:
                val = body["config_json"]
                updates["config_json"] = _json.dumps(val) if val is not None else None
            if "is_active" in body and body["is_active"] is not None:
                updates["is_active"] = int(body["is_active"])

            if not updates:
                raise ForgeError("No updatable fields provided", status_code=400)

            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            updates["id"] = skill_id
            sql.execute_write(
                f"UPDATE query_skills SET {set_clause}, updated_at = :updated_at WHERE id = :id",
                {**updates, "updated_at": datetime.now(timezone.utc)},
            )
            rows = sql.execute_query_mappings(
                "SELECT id, workspace_id, name, skill_type, query_id, config_json, is_active, created_by, created_at, updated_at FROM query_skills WHERE id = :id",
                {"id": skill_id},
            )
            return {"data": _serialize_row(dict(rows[0])) if rows else {"id": skill_id}}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skills update failed skill_id=%s", skill_id)
            return {"error": "skills update failed"}, 500

    @token_required
    def delete(self, skill_id: str):
        try:
            workspace_id = extract_workspace_id()
            from app.adapters.mysql_sql_executor import ForgeMetaSQL

            sql = ForgeMetaSQL()
            existing = sql.execute_query_mappings(
                "SELECT id FROM query_skills WHERE id = :id AND workspace_id = :ws LIMIT 1",
                {"id": skill_id, "ws": workspace_id},
            )
            if not existing:
                raise ForgeError(f"Skill {skill_id} not found", status_code=404)
            sql.execute_write(
                "UPDATE query_skills SET is_active = 0, updated_at = :now WHERE id = :id",
                {"now": datetime.now(timezone.utc), "id": skill_id},
            )
            return {"message": "skill deactivated", "skill_id": skill_id}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skills delete failed skill_id=%s", skill_id)
            return {"error": "skills delete failed"}, 500


@skills_ns.route("/<string:skill_id>/execute")
class SkillExecute(ForgeResource):
    @token_required
    @skills_ns.response(201, "Execution queued", _execute_response_model)
    def post(self, skill_id: str):
        try:
            workspace_id = extract_workspace_id()
            user_id = getattr(g, "user_id", None) or "unknown"

            from app.adapters.mysql_sql_executor import ForgeMetaSQL

            sql = ForgeMetaSQL()
            existing = sql.execute_query_mappings(
                "SELECT id FROM query_skills WHERE id = :id AND workspace_id = :ws AND is_active = 1 LIMIT 1",
                {"id": skill_id, "ws": workspace_id},
            )
            if not existing:
                raise ForgeError(f"Skill {skill_id} not found or inactive", status_code=404)

            execution_id = str(uuid.uuid4())
            job_id = str(uuid.uuid4())

            sql.execute_write(
                """
                INSERT INTO skill_executions (id, skill_id, workspace_id, job_id, status, triggered_by, created_at)
                VALUES (:id, :skill_id, :workspace_id, :job_id, 'queued', :triggered_by, CURRENT_TIMESTAMP)
                """,
                {
                    "id": execution_id,
                    "skill_id": skill_id,
                    "workspace_id": workspace_id,
                    "job_id": job_id,
                    "triggered_by": str(user_id),
                },
            )

            from app.tasks.skill_runner import execute_skill_task

            execute_skill_task.apply_async(
                kwargs={
                    "skill_id": skill_id,
                    "workspace_id": workspace_id,
                    "execution_id": execution_id,
                    "triggered_by": str(user_id),
                },
                task_id=job_id,
            )

            return {
                "execution_id": execution_id,
                "job_id": job_id,
                "status": "queued",
            }, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skills execute failed skill_id=%s", skill_id)
            return {"error": "skills execute failed"}, 500


@skills_ns.route("/<string:skill_id>/executions")
class SkillExecutionList(ForgeResource):
    @token_required
    @skills_ns.doc(params={"page": "Page number (default 1)", "page_size": "Page size (default 20, max 100)"})
    def get(self, skill_id: str):
        try:
            workspace_id = extract_workspace_id()
            page = int_arg("page", 1)
            page_size = min(int_arg("page_size", 20), 100)
            offset = (page - 1) * page_size

            from app.adapters.mysql_sql_executor import ForgeMetaSQL

            sql = ForgeMetaSQL()
            rows = sql.execute_query_mappings(
                """
                SELECT id, skill_id, workspace_id, schedule_id, job_id, status,
                       triggered_by, started_at, completed_at, error_message, result_json, created_at
                FROM skill_executions
                WHERE skill_id = :skill_id AND workspace_id = :ws
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """,
                {"skill_id": skill_id, "ws": workspace_id, "limit": page_size, "offset": offset},
            )
            total_rows = sql.execute_query_mappings(
                "SELECT COUNT(*) AS cnt FROM skill_executions WHERE skill_id = :skill_id AND workspace_id = :ws",
                {"skill_id": skill_id, "ws": workspace_id},
            )
            total = int((total_rows[0]["cnt"] if total_rows else 0) or 0)
            return {
                "data": [_serialize_row(dict(r)) for r in rows],
                "page": page,
                "page_size": page_size,
                "total": total,
            }, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skill executions list failed skill_id=%s", skill_id)
            return {"error": "skill executions list failed"}, 500


@skills_ns.route("/schedules")
class SkillScheduleList(ForgeResource):
    @token_required
    @skills_ns.doc(params={"page": "Page number (default 1)", "page_size": "Page size (default 20, max 100)"})
    def get(self):
        try:
            workspace_id = extract_workspace_id()
            page = int_arg("page", 1)
            page_size = min(int_arg("page_size", 20), 100)
            offset = (page - 1) * page_size

            from app.adapters.mysql_sql_executor import ForgeMetaSQL

            sql = ForgeMetaSQL()
            rows = sql.execute_query_mappings(
                """
                SELECT id, skill_id, workspace_id, cron_expr, timezone,
                       next_run_at, last_run_at, is_active, created_at, updated_at
                FROM skill_schedules
                WHERE workspace_id = :ws
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
                """,
                {"ws": workspace_id, "limit": page_size, "offset": offset},
            )
            total_rows = sql.execute_query_mappings(
                "SELECT COUNT(*) AS cnt FROM skill_schedules WHERE workspace_id = :ws",
                {"ws": workspace_id},
            )
            total = int((total_rows[0]["cnt"] if total_rows else 0) or 0)
            return {
                "data": [_serialize_row(dict(r)) for r in rows],
                "page": page,
                "page_size": page_size,
                "total": total,
            }, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skill schedules list failed")
            return {"error": "skill schedules list failed"}, 500


@skills_ns.route("/<string:skill_id>/schedules")
class SkillScheduleCreate(ForgeResource):
    @token_required
    @skills_ns.expect(_schedule_create_model, validate=False)
    def post(self, skill_id: str):
        try:
            workspace_id = extract_workspace_id()
            body: Dict[str, Any] = request.get_json(silent=True) or {}

            cron_expr = str(body.get("cron_expr") or "").strip()
            if not cron_expr:
                raise ForgeError("cron_expr is required", status_code=400)

            timezone_str = str(body.get("timezone") or "UTC").strip() or "UTC"
            next_run_at_raw = body.get("next_run_at") or None
            is_active = int(body.get("is_active", 1))

            from app.adapters.mysql_sql_executor import ForgeMetaSQL

            sql = ForgeMetaSQL()
            existing = sql.execute_query_mappings(
                "SELECT id FROM query_skills WHERE id = :id AND workspace_id = :ws AND is_active = 1 LIMIT 1",
                {"id": skill_id, "ws": workspace_id},
            )
            if not existing:
                raise ForgeError(f"Skill {skill_id} not found or inactive", status_code=404)

            schedule_id = str(uuid.uuid4())
            sql.execute_write(
                """
                INSERT INTO skill_schedules (id, skill_id, workspace_id, cron_expr, timezone, next_run_at, is_active, created_at)
                VALUES (:id, :skill_id, :workspace_id, :cron_expr, :timezone, :next_run_at, :is_active, CURRENT_TIMESTAMP)
                """,
                {
                    "id": schedule_id,
                    "skill_id": skill_id,
                    "workspace_id": workspace_id,
                    "cron_expr": cron_expr,
                    "timezone": timezone_str,
                    "next_run_at": next_run_at_raw,
                    "is_active": is_active,
                },
            )
            rows = sql.execute_query_mappings(
                "SELECT id, skill_id, workspace_id, cron_expr, timezone, next_run_at, last_run_at, is_active, created_at, updated_at FROM skill_schedules WHERE id = :id",
                {"id": schedule_id},
            )
            return {"data": _serialize_row(dict(rows[0])) if rows else {"id": schedule_id}}, 201
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skill schedule create failed skill_id=%s", skill_id)
            return {"error": "skill schedule create failed"}, 500


@skills_ns.route("/schedules/<string:schedule_id>")
class SkillScheduleDetail(ForgeResource):
    @token_required
    @skills_ns.expect(_schedule_update_model, validate=False)
    def put(self, schedule_id: str):
        try:
            workspace_id = extract_workspace_id()
            body: Dict[str, Any] = request.get_json(silent=True) or {}

            from app.adapters.mysql_sql_executor import ForgeMetaSQL

            sql = ForgeMetaSQL()
            existing = sql.execute_query_mappings(
                "SELECT id FROM skill_schedules WHERE id = :id AND workspace_id = :ws LIMIT 1",
                {"id": schedule_id, "ws": workspace_id},
            )
            if not existing:
                raise ForgeError(f"Schedule {schedule_id} not found", status_code=404)

            updates: Dict[str, Any] = {}
            if "cron_expr" in body and body["cron_expr"] is not None:
                updates["cron_expr"] = str(body["cron_expr"]).strip()
            if "timezone" in body and body["timezone"] is not None:
                updates["timezone"] = str(body["timezone"]).strip()
            if "next_run_at" in body:
                updates["next_run_at"] = body["next_run_at"] or None
            if "is_active" in body and body["is_active"] is not None:
                updates["is_active"] = int(body["is_active"])

            if not updates:
                raise ForgeError("No updatable fields provided", status_code=400)

            set_clause = ", ".join(f"{k} = :{k}" for k in updates)
            updates["id"] = schedule_id
            sql.execute_write(
                f"UPDATE skill_schedules SET {set_clause}, updated_at = :updated_at WHERE id = :id",
                {**updates, "updated_at": datetime.now(timezone.utc)},
            )
            rows = sql.execute_query_mappings(
                "SELECT id, skill_id, workspace_id, cron_expr, timezone, next_run_at, last_run_at, is_active, created_at, updated_at FROM skill_schedules WHERE id = :id",
                {"id": schedule_id},
            )
            return {"data": _serialize_row(dict(rows[0])) if rows else {"id": schedule_id}}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skill schedule update failed schedule_id=%s", schedule_id)
            return {"error": "skill schedule update failed"}, 500


@skills_ns.route("/scheduler/status")
class SchedulerStatus(ForgeResource):
    @token_required
    def get(self):
        """
        Return Beat scheduler health. Used by ops dashboards and
        the SkillBuilder UI to warn when the scheduler is not running.
        """
        try:
            health = get_scheduler_health()
            status_code = 200 if health["healthy"] else 503
            return health, status_code
        except Exception:
            logger.exception("scheduler status check failed")
            return {"error": "scheduler status check failed"}, 500


@skills_ns.route("/<string:skill_id>/schedule/upcoming")
class SkillScheduleUpcoming(ForgeResource):
    @token_required
    def get(self, skill_id: str):
        """
        Return the next N scheduled run times for a skill.
        Used by the SkillBuilder UI to preview when a skill will next fire.

        Query params:
          n  — number of upcoming runs to return (default 5, max 20)
        """
        try:
            workspace_id = extract_workspace_id()
            from app.adapters.mysql_sql_executor import ForgeMetaSQL

            sql = ForgeMetaSQL()
            schedule_rows = sql.execute_query_mappings(
                """
                SELECT cron_expr, timezone FROM skill_schedules
                WHERE skill_id = :skill_id AND workspace_id = :ws AND is_active = 1
                ORDER BY created_at DESC LIMIT 1
                """,
                {"skill_id": skill_id, "ws": workspace_id},
            )
            if not schedule_rows:
                return {"upcoming": [], "reason": "No schedule configured."}, 200

            row = schedule_rows[0]
            cron_expr = str(row["cron_expr"] or "")
            timezone_str = str(row["timezone"] or "UTC")

            if not cron_expr:
                return {"upcoming": [], "reason": "No cron expression configured."}, 200

            n = min(int(request.args.get("n", 5) or 5), 20)
            runs = next_n_runs(expression=cron_expr, timezone_name=timezone_str, n=n)
            return {
                "upcoming": runs,
                "cron_expr": cron_expr,
                "timezone": timezone_str,
            }, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skill schedule upcoming failed skill_id=%s", skill_id)
            return {"error": "skill schedule upcoming failed"}, 500


@skills_ns.route("/<string:skill_id>/acknowledge")
class SkillAlertAcknowledge(ForgeResource):
    @token_required
    def post(self, skill_id: str):
        """
        Manually acknowledge an alert. Sets alert_acknowledged_at to now.
        Only relevant for threshold_alert skills with resolution_mode="manual".
        """
        try:
            workspace_id = extract_workspace_id()
            from app.adapters.mysql_sql_executor import ForgeMetaSQL

            sql = ForgeMetaSQL()
            rows = sql.execute_query_mappings(
                "SELECT id, skill_type FROM query_skills WHERE id = :id AND workspace_id = :ws AND is_active = 1 LIMIT 1",
                {"id": skill_id, "ws": workspace_id},
            )
            if not rows:
                raise ForgeError(f"Skill {skill_id} not found", status_code=404)

            if str(rows[0]["skill_type"]) != "threshold_alert":
                return {"error": "Only threshold_alert skills support acknowledgement."}, 400

            now = datetime.now(timezone.utc)
            sql.execute_write(
                "UPDATE query_skills SET alert_acknowledged_at = :now WHERE id = :id",
                {"now": now, "id": skill_id},
            )
            return {"acknowledged": True, "acknowledged_at": now.isoformat()}, 200
        except ForgeError as exc:
            return exc.to_dict(), exc.status_code
        except Exception:
            logger.exception("skill acknowledge failed skill_id=%s", skill_id)
            return {"error": "skill acknowledge failed"}, 500


@skills_ns.route("/schedule/validate")
class ScheduleValidate(ForgeResource):
    @token_required
    def post(self):
        """
        Validate a cron expression and return next 5 run times.
        Called by the SkillBuilder UI on every cron expression change.
        """
        try:
            body: Dict[str, Any] = request.get_json(silent=True) or {}
            expression = str(body.get("cron_expression") or "").strip()
            timezone_name = str(body.get("timezone") or "UTC").strip() or "UTC"

            errors = validate_cron(expression, timezone_name)
            if errors:
                return {"valid": False, "errors": errors, "upcoming": []}, 200

            upcoming = next_n_runs(expression, timezone_name, n=5)
            return {"valid": True, "errors": [], "upcoming": upcoming}, 200
        except Exception:
            logger.exception("schedule validate failed")
            return {"error": "schedule validate failed"}, 500


__all__ = ["skills_ns"]
