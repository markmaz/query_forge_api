from __future__ import annotations

import json
import uuid
from typing import Any, Callable, Dict, Optional

from app.exceptions.forge_error import ForgeError


class ExecutionJobService:
    def __init__(
        self,
        *,
        client_factory: Callable[[], Any],
        utc_now_iso: Callable[[], str],
        ttl_s: int,
    ) -> None:
        self._client_factory = client_factory
        self._utc_now_iso = utc_now_iso
        self._ttl_s = ttl_s

    def create_job(self, payload: Dict[str, Any]) -> str:
        job_id = uuid.uuid4().hex
        self.put_job(job_id, payload)
        return job_id

    def put_job(self, job_id: str, payload: Dict[str, Any]) -> None:
        data = dict(payload)
        data.setdefault("created_at", self._utc_now_iso())
        encoded = json.dumps(data, default=str)
        self._client_factory().setex(self.job_key(job_id), self._ttl_s, encoded)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        raw = self._client_factory().get(self.job_key(job_id))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def get_job_for_workspace(self, workspace_id: str, job_id: str) -> Dict[str, Any]:
        job = self.get_job(job_id)
        if not job or job.get("workspace_id") != workspace_id:
            raise ForgeError("Execution job not found", status_code=404)
        return job

    @staticmethod
    def job_key(job_id: str) -> str:
        return f"qf:exec:{job_id}"
