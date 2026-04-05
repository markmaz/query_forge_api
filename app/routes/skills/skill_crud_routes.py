from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from flask import g, request
from flask_restx import Resource

from app.decorators.ownership import require_ownership
from app.decorators.rbac import require_access
from app.decorators.security import token_required
from app.exceptions.forge_error import ForgeError
from app.routes.request_helpers import extract_workspace_id, int_arg, require_user_id

from .base import skills_ns
from .helpers import (
    backend_skill_type,
    config_from_request,
    normalize_skill_row,
    normalize_skill_run_row,
    sync_skill_schedule,
)
from .models import execute_response_model, skill_create_model, skill_update_model


@skills_ns.route("")
class SkillList(Resource):
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
        search = str(request.args.get("q") or "").strip().lower()
        status_filter = str(request.args.get("status") or "").strip().lower()
        skill_type_filter = str(request.args.get("skill_type") or "").strip()
        page = int_arg("page", 1)
        page_size = min(int_arg("page_size", 20), 100)

        from app.adapters.mysql_sql_executor import ForgeMetaSQL

        sql = ForgeMetaSQL()
        rows = sql.execute_query_mappings(
            """
            SELECT qs.id, qs.workspace_id, qs.name, qs.skill_type, qs.query_id, qs.config_json,
                   qs.is_active, qs.created_by, qs.created_at, qs.updated_at,
                   MAX(se.started_at) AS last_run_at,
                   COUNT(se.id) AS run_count
            FROM query_skills
            qs
            LEFT JOIN skill_executions se
              ON se.skill_id = qs.id
             AND se.workspace_id = qs.workspace_id
            WHERE qs.workspace_id = :ws
            GROUP BY qs.id, qs.workspace_id, qs.name, qs.skill_type, qs.query_id, qs.config_json,
                     qs.is_active, qs.created_by, qs.created_at, qs.updated_at
            ORDER BY qs.created_at DESC
            """,
            {"ws": workspace_id},
        )
        normalized = [normalize_skill_row(dict(r)) for r in rows]
        if search:
            normalized = [
                row
                for row in normalized
                if search in str(row.get("name") or "").lower()
                or search in str(row.get("description") or "").lower()
            ]
        if status_filter:
            normalized = [
                row
                for row in normalized
                if str(row.get("status") or "").lower() == status_filter
            ]
        if skill_type_filter:
            normalized = [
                row
                for row in normalized
                if str(row.get("skill_type") or "") == skill_type_filter
            ]

        total = len(normalized)
        offset = (page - 1) * page_size
        page_rows = normalized[offset : offset + page_size]
        return {
            "data": page_rows,
            "page": page,
            "page_size": page_size,
            "total": total,
        }, 200

    @token_required
    @require_access("skills", role="admin")
    @skills_ns.expect(skill_create_model, validate=False)
    def post(self):
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
        config_json, resolved_backend_type, is_active = config_from_request(body)
        if is_active is None:
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
                "skill_type": resolved_backend_type or skill_type,
                "query_id": query_id,
                "config_json": config_str,
                "is_active": is_active,
                "created_by": user_id,
                "now": datetime.now(timezone.utc),
            },
        )
        sync_skill_schedule(
            sql,
            skill_id=skill_id,
            workspace_id=workspace_id,
            config_json=config_json,
            skill_is_active=is_active,
        )
        rows = sql.execute_query_mappings(
            """
            SELECT qs.id, qs.workspace_id, qs.name, qs.skill_type, qs.query_id, qs.config_json,
                   qs.is_active, qs.created_by, qs.created_at, qs.updated_at,
                   NULL AS last_run_at, 0 AS run_count
            FROM query_skills qs
            WHERE qs.id = :id
            """,
            {"id": skill_id},
        )
        return {
            "data": normalize_skill_row(dict(rows[0])) if rows else {"id": skill_id}
        }, 201


@skills_ns.route("/<string:skill_id>")
class SkillDetail(Resource):
    @token_required
    @require_access("skills")
    @require_ownership("QuerySkill", "skill_id", "skills:admin", check_read=True)
    def get(self, skill_id: str):
        workspace_id = extract_workspace_id()
        from app.adapters.mysql_sql_executor import ForgeMetaSQL

        sql = ForgeMetaSQL()
        rows = sql.execute_query_mappings(
            """
            SELECT qs.id, qs.workspace_id, qs.name, qs.skill_type, qs.query_id, qs.config_json,
                   qs.is_active, qs.created_by, qs.created_at, qs.updated_at,
                   MAX(se.started_at) AS last_run_at,
                   COUNT(se.id) AS run_count
            FROM query_skills qs
            LEFT JOIN skill_executions se
              ON se.skill_id = qs.id
             AND se.workspace_id = qs.workspace_id
            WHERE qs.id = :id AND qs.workspace_id = :ws
            GROUP BY qs.id, qs.workspace_id, qs.name, qs.skill_type, qs.query_id, qs.config_json,
                     qs.is_active, qs.created_by, qs.created_at, qs.updated_at
            LIMIT 1
            """,
            {"id": skill_id, "ws": workspace_id},
        )
        if not rows:
            raise ForgeError(f"Skill {skill_id} not found", status_code=404)
        return {"data": normalize_skill_row(dict(rows[0]))}, 200

    @token_required
    @require_access("skills", role="admin")
    @require_ownership("QuerySkill", "skill_id", "skills:admin", check_read=True)
    @skills_ns.expect(skill_update_model, validate=False)
    def put(self, skill_id: str):
        workspace_id = extract_workspace_id()
        body: Dict[str, Any] = request.get_json(silent=True) or {}

        from app.adapters.mysql_sql_executor import ForgeMetaSQL
        import json as _json

        sql = ForgeMetaSQL()
        existing_rows = sql.execute_query_mappings(
            """
            SELECT id, skill_type, config_json, is_active
            FROM query_skills
            WHERE id = :id AND workspace_id = :ws
            LIMIT 1
            """,
            {"id": skill_id, "ws": workspace_id},
        )
        if not existing_rows:
            raise ForgeError(f"Skill {skill_id} not found", status_code=404)
        existing = dict(existing_rows[0])

        updates: Dict[str, Any] = {}
        if "name" in body and body["name"] is not None:
            updates["name"] = str(body["name"]).strip()
        if "skill_type" in body and body["skill_type"] is not None:
            updates["skill_type"] = backend_skill_type(str(body["skill_type"]).strip())
        if "query_id" in body:
            updates["query_id"] = body["query_id"] or None
        if {
            "config_json",
            "config",
            "description",
            "status",
            "trigger",
            "conditions",
            "actions",
            "workflow",
            "query_name",
            "condition_mode",
            "check_mode",
            "alert_mode",
            "resolution_mode",
            "severity",
            "is_active",
        } & set(body):
            next_config, _, next_is_active = config_from_request(
                body,
                existing_row=existing,
            )
            updates["config_json"] = (
                _json.dumps(next_config) if next_config is not None else None
            )
            if next_is_active is not None:
                updates["is_active"] = next_is_active
        elif "is_active" in body and body["is_active"] is not None:
            updates["is_active"] = int(body["is_active"])

        if not updates:
            raise ForgeError("No updatable fields provided", status_code=400)

        set_clause = ", ".join(f"{k} = :{k}" for k in updates)
        updates["id"] = skill_id
        sql.execute_write(
            f"UPDATE query_skills SET {set_clause}, updated_at = :updated_at WHERE id = :id",
            {**updates, "updated_at": datetime.now(timezone.utc)},
        )
        next_config_json = updates.get("config_json", existing.get("config_json"))
        next_is_active_value = updates.get("is_active", existing.get("is_active"))
        sync_skill_schedule(
            sql,
            skill_id=skill_id,
            workspace_id=workspace_id,
            config_json=next_config_json,
            skill_is_active=int(next_is_active_value or 0),
        )
        rows = sql.execute_query_mappings(
            """
            SELECT qs.id, qs.workspace_id, qs.name, qs.skill_type, qs.query_id, qs.config_json,
                   qs.is_active, qs.created_by, qs.created_at, qs.updated_at,
                   MAX(se.started_at) AS last_run_at,
                   COUNT(se.id) AS run_count
            FROM query_skills qs
            LEFT JOIN skill_executions se
              ON se.skill_id = qs.id
             AND se.workspace_id = qs.workspace_id
            WHERE qs.id = :id
            GROUP BY qs.id, qs.workspace_id, qs.name, qs.skill_type, qs.query_id, qs.config_json,
                     qs.is_active, qs.created_by, qs.created_at, qs.updated_at
            """,
            {"id": skill_id},
        )
        return {
            "data": normalize_skill_row(dict(rows[0])) if rows else {"id": skill_id}
        }, 200

    @token_required
    @require_access("skills", role="admin")
    @require_ownership("QuerySkill", "skill_id", "skills:admin", check_read=True)
    @skills_ns.expect(skill_update_model, validate=False)
    def patch(self, skill_id: str):
        return self.put(skill_id=skill_id)

    @token_required
    @require_access("skills", role="admin")
    @require_ownership("QuerySkill", "skill_id", "skills:admin", check_read=True)
    def delete(self, skill_id: str):
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
        sql.execute_write(
            """
            UPDATE skill_schedules
            SET is_active = 0, next_run_at = NULL, updated_at = :now
            WHERE skill_id = :skill_id AND workspace_id = :ws
            """,
            {"now": datetime.now(timezone.utc), "skill_id": skill_id, "ws": workspace_id},
        )
        return {"message": "skill deactivated", "skill_id": skill_id}, 200


@skills_ns.route("/<string:skill_id>/execute")
class SkillExecute(Resource):
    @token_required
    @require_access("skills")
    @require_ownership("QuerySkill", "skill_id", "skills:admin", check_read=True)
    @skills_ns.response(201, "Execution queued", execute_response_model)
    def post(self, skill_id: str):
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


@skills_ns.route("/<string:skill_id>/executions")
class SkillExecutionList(Resource):
    @token_required
    @require_access("skills")
    @require_ownership("QuerySkill", "skill_id", "skills:admin", check_read=True)
    @skills_ns.doc(
        params={
            "page": "Page number (default 1)",
            "page_size": "Page size (default 20, max 100)",
        }
    )
    def get(self, skill_id: str):
        workspace_id = extract_workspace_id()
        page = int_arg("page", 1)
        page_size = min(int_arg("page_size", 20), 100)
        offset = (page - 1) * page_size

        from app.adapters.mysql_sql_executor import ForgeMetaSQL

        sql = ForgeMetaSQL()
        rows = sql.execute_query_mappings(
            """
            SELECT id, skill_id, workspace_id, schedule_id, job_id, status,
                   triggered_by, started_at, completed_at AS finished_at,
                   CASE
                     WHEN started_at IS NOT NULL AND completed_at IS NOT NULL
                     THEN TIMESTAMPDIFF(MICROSECOND, started_at, completed_at) DIV 1000
                     ELSE NULL
                   END AS duration_ms,
                   COALESCE(error_message, CASE WHEN status = 'success' THEN 'Run complete.' ELSE 'Run queued.' END) AS message,
                   error_message, result_json, created_at
            FROM skill_executions
            WHERE skill_id = :skill_id AND workspace_id = :ws
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """,
            {
                "skill_id": skill_id,
                "ws": workspace_id,
                "limit": page_size,
                "offset": offset,
            },
        )
        total_rows = sql.execute_query_mappings(
            "SELECT COUNT(*) AS cnt FROM skill_executions WHERE skill_id = :skill_id AND workspace_id = :ws",
            {"skill_id": skill_id, "ws": workspace_id},
        )
        total = int((total_rows[0]["cnt"] if total_rows else 0) or 0)
        return {
            "data": [normalize_skill_run_row(dict(r)) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }, 200


@skills_ns.route("/<string:skill_id>/runs")
class SkillRunListAlias(Resource):
    @token_required
    @require_access("skills")
    @require_ownership("QuerySkill", "skill_id", "skills:admin", check_read=True)
    def get(self, skill_id: str):
        return SkillExecutionList().get(skill_id=skill_id)
