from __future__ import annotations

import logging

from celery import shared_task

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.services.forge_match.mapping_service import ForgeMatchMappingService

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="qf.forge_match.analyze_session")
def analyze_forge_match_session_task(
    self,
    *,
    job_id: str,
    workspace_id: str,
    session_id: str,
    top_n: int = 8,
    domain_id: int | None = None,
    vertical_norm: str | None = None,
    force: bool = False,
) -> dict:
    del self
    sql = ForgeMetaSQL()
    service = ForgeMatchMappingService(sql=sql)
    try:
        result = service.run_analyze_job(
            workspace_id=workspace_id,
            session_id=session_id,
            top_n=top_n,
            domain_id=domain_id,
            vertical_norm=vertical_norm,
            force=force,
            job_id=job_id,
        )
        return {
            "job_id": job_id,
            "session_id": session_id,
            "status": result.get("status"),
            "analyzed_count": int(result.get("analyzed_count") or 0),
            "failed_count": int(result.get("failed_count") or 0),
        }
    except Exception:
        logger.exception("ForgeMatch analyze task failed job_id=%s session_id=%s", job_id, session_id)
        raise


__all__ = ["analyze_forge_match_session_task"]
