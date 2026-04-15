from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from flask import request
from flask_restx import Resource

from app.decorators.ownership import require_ownership
from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import extract_workspace_id, int_arg
from app.skills.schedule_utils import get_scheduler_health, next_n_runs, validate_cron

from .base import skills_ns
from .helpers import (
    cron_expr_from_validate_request,
    resolve_next_run_at,
    serialize_schedule_row,
)
from .models import schedule_create_model, schedule_update_model


@skills_ns.route("/schedules")
class SkillScheduleList(Resource):
    @token_required
    @require_access("skills")
    @skills_ns.doc(
        params={
            "page": "Page number (default 1)",
            "page_size": "Page size (default 20, max 100)",
        }
    )
    def get(self):
        workspace_id = extract_workspace_id()
        page = int_arg("page", 1)
        page_size = min(int_arg("page_size", 20), 100)
        offset = (page - 1) * page_size

        from app.adapters.mysql_sql_executor import ForgeMetaSQL

        sql = ForgeMetaSQL()
        rows = sql.execute_query_mappings(
            """
            SELECT id, skill_id, workspace_id, cron_expr, timezone,
                   next_run_at, last_run_at, is_active, catch_up, created_at, updated_at
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
            "data": [serialize_schedule_row(dict(r)) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }, 200


@skills_ns.route("/<string:skill_id>/schedules")
class SkillScheduleCreate(Resource):
    @token_required
    @require_access("skills", role="admin")
    @require_ownership("QuerySkill", "skill_id", "skills:admin", check_read=True)
    @skills_ns.expect(schedule_create_model, validate=False)
    def post(self, skill_id: str):
        workspace_id = extract_workspace_id()
        body: Dict[str, Any] = request.get_json(silent=True) or {}

        cron_expr = str(body.get("cron_expr") or "").strip()
        if not cron_expr:
            raise ForgeError("cron_expr is required", status_code=400)

        timezone_str = str(body.get("timezone") or "UTC").strip() or "UTC"
        is_active = int(body.get("is_active", 1))
        errors = validate_cron(cron_expr, timezone_str)
        if errors:
            raise ForgeError("; ".join(errors), status_code=400)
        next_run_at = (
            None
            if not is_active
            else resolve_next_run_at(
                cron_expr=cron_expr,
                timezone_name=timezone_str,
                next_run_at_raw=body.get("next_run_at"),
            )
        )

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
                "next_run_at": next_run_at,
                "is_active": is_active,
            },
        )
        rows = sql.execute_query_mappings(
            "SELECT id, skill_id, workspace_id, cron_expr, timezone, next_run_at, last_run_at, is_active, catch_up, created_at, updated_at FROM skill_schedules WHERE id = :id",
            {"id": schedule_id},
        )
        return {
            "data": serialize_schedule_row(dict(rows[0])) if rows else {"id": schedule_id}
        }, 201


@skills_ns.route("/schedules/<string:schedule_id>")
class SkillScheduleDetail(Resource):
    @token_required
    @require_access("skills", role="admin")
    @skills_ns.expect(schedule_update_model, validate=False)
    def put(self, schedule_id: str):
        workspace_id = extract_workspace_id()
        body: Dict[str, Any] = request.get_json(silent=True) or {}

        from app.adapters.mysql_sql_executor import ForgeMetaSQL

        sql = ForgeMetaSQL()
        existing = sql.execute_query_mappings(
            """
            SELECT id, cron_expr, timezone, next_run_at, is_active
            FROM skill_schedules
            WHERE id = :id AND workspace_id = :ws
            LIMIT 1
            """,
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

        next_cron_expr = str(
            updates.get("cron_expr") or existing[0].get("cron_expr") or ""
        ).strip()
        next_timezone = (
            str(updates.get("timezone") or existing[0].get("timezone") or "UTC").strip()
            or "UTC"
        )
        next_is_active = int(
            updates.get("is_active", existing[0].get("is_active") or 0) or 0
        )
        errors = validate_cron(next_cron_expr, next_timezone)
        if errors:
            raise ForgeError("; ".join(errors), status_code=400)
        updates["next_run_at"] = (
            None
            if not next_is_active
            else resolve_next_run_at(
                cron_expr=next_cron_expr,
                timezone_name=next_timezone,
                next_run_at_raw=body.get("next_run_at")
                if "next_run_at" in body
                else None,
            )
        )

        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["id"] = schedule_id
        sql.execute_write(
            f"UPDATE skill_schedules SET {set_clause}, updated_at = :updated_at WHERE id = :id",
            {**updates, "updated_at": datetime.now(timezone.utc)},
        )
        rows = sql.execute_query_mappings(
            "SELECT id, skill_id, workspace_id, cron_expr, timezone, next_run_at, last_run_at, is_active, catch_up, created_at, updated_at FROM skill_schedules WHERE id = :id",
            {"id": schedule_id},
        )
        return {
            "data": serialize_schedule_row(dict(rows[0])) if rows else {"id": schedule_id}
        }, 200


@skills_ns.route("/scheduler/status")
class SchedulerStatus(Resource):
    @token_required
    @require_access("skills")
    def get(self):
        health = get_scheduler_health()
        status_code = 200 if health["healthy"] else 503
        return health, status_code


@skills_ns.route("/<string:skill_id>/schedule/upcoming")
class SkillScheduleUpcoming(Resource):
    @token_required
    @require_access("skills")
    def get(self, skill_id: str):
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


@skills_ns.route("/<string:skill_id>/acknowledge")
class SkillAlertAcknowledge(Resource):
    @token_required
    @require_access("skills")
    @require_ownership("QuerySkill", "skill_id", "skills:admin", check_read=True)
    def post(self, skill_id: str):
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
            return {
                "error": "Only threshold_alert skills support acknowledgement."
            }, 400

        now = datetime.now(timezone.utc)
        sql.execute_write(
            "UPDATE query_skills SET alert_acknowledged_at = :now WHERE id = :id",
            {"now": now, "id": skill_id},
        )
        return {"acknowledged": True, "acknowledged_at": now.isoformat()}, 200


@skills_ns.route("/schedule/validate")
class ScheduleValidate(Resource):
    @token_required
    @require_access("skills")
    def post(self):
        body: Dict[str, Any] = request.get_json(silent=True) or {}
        expression, timezone_name = cron_expr_from_validate_request(body)

        errors = validate_cron(expression, timezone_name)
        if errors:
            return {
                "valid": False,
                "errors": errors,
                "upcoming": [],
                "cron_expression": expression,
            }, 200

        upcoming = next_n_runs(expression, timezone_name, n=5)
        return {
            "valid": True,
            "errors": [],
            "upcoming": upcoming,
            "cron_expression": expression,
            "timezone": timezone_name,
        }, 200
