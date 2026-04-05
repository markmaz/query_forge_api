from __future__ import annotations

from flask_restx import fields

from .base import skills_ns

skill_create_model = skills_ns.model(
    "SkillCreate",
    {
        "name": fields.String(required=True),
        "skill_type": fields.String(required=True),
        "query_id": fields.String(required=False),
        "config_json": fields.Raw(required=False),
        "is_active": fields.Integer(required=False, default=1),
    },
)

skill_update_model = skills_ns.model(
    "SkillUpdate",
    {
        "name": fields.String(required=False),
        "skill_type": fields.String(required=False),
        "query_id": fields.String(required=False),
        "config_json": fields.Raw(required=False),
        "is_active": fields.Integer(required=False),
    },
)

schedule_create_model = skills_ns.model(
    "SkillScheduleCreate",
    {
        "cron_expr": fields.String(required=True),
        "timezone": fields.String(required=False, default="UTC"),
        "next_run_at": fields.String(required=False),
        "is_active": fields.Integer(required=False, default=1),
    },
)

schedule_update_model = skills_ns.model(
    "SkillScheduleUpdate",
    {
        "cron_expr": fields.String(required=False),
        "timezone": fields.String(required=False),
        "next_run_at": fields.String(required=False),
        "is_active": fields.Integer(required=False),
    },
)

execute_response_model = skills_ns.model(
    "SkillExecuteResponse",
    {
        "execution_id": fields.String(required=True),
        "job_id": fields.String(required=True),
        "status": fields.String(required=True),
    },
)
