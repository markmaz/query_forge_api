from __future__ import annotations

from app.services.execution.execution_job_service import ExecutionJobService


class _FakeValkey:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def setex(self, key, _ttl, value):
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)


def test_execution_job_service_round_trips_payload() -> None:
    client = _FakeValkey()
    service = ExecutionJobService(client_factory=lambda: client, utc_now_iso=lambda: "2026-03-30T00:00:00Z", ttl_s=10)

    job_id = service.create_job({"workspace_id": "ws-1", "statement_id": "stmt-1"})
    job = service.get_job(job_id)

    assert job is not None
    assert job["workspace_id"] == "ws-1"
    assert job["statement_id"] == "stmt-1"
    assert job["created_at"] == "2026-03-30T00:00:00Z"


def test_execution_job_service_key_format() -> None:
    assert ExecutionJobService.job_key("abc") == "qf:exec:abc"
