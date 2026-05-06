from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch


from app.services.admin.health_service import AdminHealthService


class _FakeSQL:
    def __init__(self, *, fail: bool = False, flowforge_metrics: Dict[str, Any] | None = None) -> None:
        self._fail = fail
        self._flowforge_metrics = flowforge_metrics or {
            "pending_notification_count": 0,
            "failed_notification_count": 0,
            "stuck_run_count": 0,
            "failed_run_count": 0,
            "schedule_backlog_count": 0,
            "failed_import_count": 0,
            "failed_export_count": 0,
            "stuck_approval_count": 0,
            "expired_artifact_count": 0,
            "artifact_retention_pending_count": 0,
        }

    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Tuple]:
        if self._fail:
            raise RuntimeError("connection refused")
        return [(1,)]

    def execute_query_mappings(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        if self._fail:
            raise RuntimeError("connection refused")
        return [dict(self._flowforge_metrics)]


_FLOWFORGE_HEALTHY = {
    "healthy": True,
    "reason": None,
    "last_dispatch_at": "2026-05-05T10:00:00+00:00",
    "seconds_since_dispatch": 12,
    "task_name": "qf.flowforge.dispatch_notifications",
}


_FLOWFORGE_STALE = {
    "healthy": False,
    "reason": "Last FlowForge worker heartbeat was 500s ago.",
    "last_dispatch_at": "2026-05-05T09:50:00+00:00",
    "seconds_since_dispatch": 500,
    "task_name": "qf.flowforge.dispatch_notifications",
}


class _OkResponse:
    status_code = 200
    text = '{"title":"qdrant"}'

    def json(self) -> Dict[str, Any]:
        return {"title": "qdrant"}

    def raise_for_status(self) -> None:
        pass


class _VllmOkResponse:
    status_code = 200
    text = '{"data":[{"id":"qwen25-7b"}]}'

    def json(self) -> Dict[str, Any]:
        return {"data": [{"id": "qwen25-7b"}]}

    def raise_for_status(self) -> None:
        pass


class _ErrorResponse:
    status_code = 503
    text = "Service Unavailable"

    def raise_for_status(self) -> None:
        from requests.exceptions import HTTPError

        raise HTTPError("503 Server Error")


def test_check_all_healthy():
    with patch("app.services.admin.health_service.requests.get") as mock_get:
        with patch.object(
            AdminHealthService,
            "check_broker",
            return_value={"status": "ok", "ok": True, "valkey": {"ping_ok": True}, "celery": {"broker_connect_ok": True}},
        ), patch("app.services.admin.health_service.get_flowforge_worker_health", return_value=_FLOWFORGE_HEALTHY):
            def _route(url: str, **kwargs: Any) -> Any:
                if "/v1/models" in url:
                    return _VllmOkResponse()
                return _OkResponse()

            mock_get.side_effect = _route
            svc = AdminHealthService(
                sql=_FakeSQL(),
                vllm_base_url="http://fake-llm:8000",
                vllm_model="qwen25-7b",
                qdrant_url="http://fake-qdrant:6333",
                mcp_resource_url="http://fake-mcp:8001",
            )
            result = svc.check_all()

    assert result["overall"] == "healthy"
    assert result["checks"]["app"]["status"] == "ok"
    assert result["checks"]["mysql"]["status"] == "ok"
    assert result["checks"]["mysql"]["latency_ms"] >= 0
    assert result["checks"]["vllm"]["status"] == "ok"
    assert result["checks"]["vllm"]["model"] == "qwen25-7b"
    assert result["checks"]["qdrant"]["status"] == "ok"
    assert result["checks"]["mcp"]["status"] == "ok"
    assert result["checks"]["mcp"]["url"] == "http://fake-mcp:8001"
    assert result["checks"]["broker"]["status"] == "ok"
    assert result["checks"]["flowforge"]["status"] == "ok"
    assert result["checks"]["flowforge"]["worker"]["task_name"] == "qf.flowforge.dispatch_notifications"


def test_check_all_mysql_down():
    with patch("app.services.admin.health_service.requests.get") as mock_get:
        with patch.object(
            AdminHealthService,
            "check_broker",
            return_value={"status": "ok", "ok": True, "valkey": {"ping_ok": True}, "celery": {"broker_connect_ok": True}},
        ), patch("app.services.admin.health_service.get_flowforge_worker_health", return_value=_FLOWFORGE_HEALTHY):
            mock_get.return_value = _OkResponse()
            svc = AdminHealthService(
                sql=_FakeSQL(fail=True),
                vllm_base_url="http://fake-llm:8000",
                qdrant_url="http://fake-qdrant:6333",
                mcp_resource_url="http://fake-mcp:8001",
            )
            result = svc.check_all()

    assert result["overall"] == "degraded"
    assert result["checks"]["mysql"]["status"] == "error"
    assert "connection refused" in result["checks"]["mysql"]["error"]


def test_check_all_vllm_down():
    with patch("app.services.admin.health_service.requests.get") as mock_get:
        with patch.object(
            AdminHealthService,
            "check_broker",
            return_value={"status": "ok", "ok": True, "valkey": {"ping_ok": True}, "celery": {"broker_connect_ok": True}},
        ), patch("app.services.admin.health_service.get_flowforge_worker_health", return_value=_FLOWFORGE_HEALTHY):
            def _route(url: str, **kwargs: Any) -> Any:
                if "/v1/models" in url:
                    raise ConnectionError("vLLM unreachable")
                return _OkResponse()

            mock_get.side_effect = _route
            svc = AdminHealthService(
                sql=_FakeSQL(),
                vllm_base_url="http://fake-llm:8000",
                qdrant_url="http://fake-qdrant:6333",
                mcp_resource_url="http://fake-mcp:8001",
            )
            result = svc.check_all()

    assert result["overall"] == "degraded"
    assert result["checks"]["vllm"]["status"] == "error"


def test_check_all_everything_down():
    """App always returns ok, so with mysql+vllm+qdrant down, overall is degraded."""
    with patch("app.services.admin.health_service.requests.get") as mock_get:
        with patch.object(
            AdminHealthService,
            "check_broker",
            return_value={"status": "error", "ok": False, "valkey": {"ping_ok": False}, "celery": {"broker_connect_ok": False}},
        ), patch("app.services.admin.health_service.get_flowforge_worker_health", return_value=_FLOWFORGE_HEALTHY):
            mock_get.side_effect = ConnectionError("unreachable")
            svc = AdminHealthService(
                sql=_FakeSQL(fail=True),
                vllm_base_url="http://fake-llm:8000",
                qdrant_url="http://fake-qdrant:6333",
                mcp_resource_url="http://fake-mcp:8001",
            )
            result = svc.check_all()

    assert result["overall"] == "degraded"
    assert result["checks"]["mysql"]["status"] == "error"
    assert result["checks"]["vllm"]["status"] == "error"
    assert result["checks"]["qdrant"]["status"] == "error"
    assert result["checks"]["app"]["status"] == "ok"


def test_check_mysql_directly():
    svc = AdminHealthService(sql=_FakeSQL(), vllm_base_url="http://fake:8000", qdrant_url="http://fake:6333")
    result = svc._check_mysql()
    assert result["status"] == "ok"
    assert result["latency_ms"] >= 0


def test_check_qdrant_directly():
    with patch("app.services.admin.health_service.requests.get") as mock_get:
        mock_get.return_value = _OkResponse()
        svc = AdminHealthService(sql=_FakeSQL(), qdrant_url="http://fake-qdrant:6333")
        result = svc._check_qdrant()

    assert result["status"] == "ok"


def test_check_mcp_directly():
    with patch("app.services.admin.health_service.requests.get") as mock_get:
        mock_get.return_value = _OkResponse()
        svc = AdminHealthService(sql=_FakeSQL(), mcp_resource_url="http://fake-mcp:8001")
        result = svc._check_mcp()

    assert result["status"] == "ok"
    assert result["url"] == "http://fake-mcp:8001"


def test_check_flowforge_reports_stale_worker_and_operational_backlog():
    svc = AdminHealthService(
        sql=_FakeSQL(
            flowforge_metrics={
                "pending_notification_count": 8,
                "failed_notification_count": 2,
                "stuck_run_count": 1,
                "failed_run_count": 3,
                "schedule_backlog_count": 4,
                "failed_import_count": 5,
                "failed_export_count": 6,
                "stuck_approval_count": 7,
                "expired_artifact_count": 8,
                "artifact_retention_pending_count": 9,
            }
        )
    )

    with patch("app.services.admin.health_service.get_flowforge_worker_health", return_value=_FLOWFORGE_STALE):
        result = svc._check_flowforge()

    assert result["status"] == "degraded"
    assert result["worker"]["healthy"] is False
    assert result["metrics"]["pending_notification_count"] == 8
    assert result["metrics"]["failed_notification_count"] == 2
    assert result["metrics"]["stuck_run_count"] == 1
    assert result["metrics"]["failed_run_count"] == 3
    assert result["metrics"]["schedule_backlog_count"] == 4
    assert result["metrics"]["failed_import_count"] == 5
    assert result["metrics"]["failed_export_count"] == 6
    assert result["metrics"]["stuck_approval_count"] == 7
    assert result["metrics"]["expired_artifact_count"] == 8
    assert result["metrics"]["artifact_retention_pending_count"] == 9
    assert any("heartbeat" in issue for issue in result["issues"])
    assert any("stuck" in issue for issue in result["issues"])
    assert any("scheduled" in issue for issue in result["issues"])
    assert any("import" in issue for issue in result["issues"])
    assert any("export" in issue for issue in result["issues"])
    assert any("approval" in issue for issue in result["issues"])
    assert any("retention" in issue for issue in result["issues"])


class _FakeValkeyClient:
    def ping(self) -> bool:
        return True


class _FakeCeleryConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        return False

    def ensure_connection(self, max_retries: int = 0) -> None:
        assert max_retries == 0


class _FakeInspector:
    def ping(self):
        return {"celery@test": {"ok": "pong"}}


class _FakeCeleryControl:
    def inspect(self, timeout: float = 1.5):
        assert timeout == 1.5
        return _FakeInspector()


class _FakeCelery:
    control = _FakeCeleryControl()

    def connection_for_write(self):
        return _FakeCeleryConnection()


def test_check_broker_ok():
    with patch("app.services.admin.health_service.valkey.Valkey") as mock_valkey:
        with patch("app.services.admin.health_service.celery", new=_FakeCelery()):
            mock_valkey.return_value = _FakeValkeyClient()
            svc = AdminHealthService(sql=_FakeSQL())
            result = svc.check_broker()

    assert result["ok"] is True
    assert result["status"] == "ok"
    assert result["valkey"]["ping_ok"] is True
    assert result["celery"]["broker_connect_ok"] is True
    assert result["celery"]["worker_ping_ok"] is True
    assert result["celery"]["workers"] == ["celery@test"]


class _NoWorkersInspector:
    def ping(self):
        return {}


class _NoWorkersCeleryControl:
    def inspect(self, timeout: float = 1.5):
        assert timeout == 1.5
        return _NoWorkersInspector()


class _NoWorkersCelery:
    control = _NoWorkersCeleryControl()

    def connection_for_write(self):
        return _FakeCeleryConnection()


def test_check_broker_is_degraded_when_broker_connects_without_workers():
    with patch("app.services.admin.health_service.valkey.Valkey") as mock_valkey:
        with patch("app.services.admin.health_service.celery", new=_NoWorkersCelery()):
            mock_valkey.return_value = _FakeValkeyClient()
            svc = AdminHealthService(sql=_FakeSQL())
            result = svc.check_broker()

    assert result["ok"] is False
    assert result["status"] == "degraded"
    assert result["valkey"]["ping_ok"] is True
    assert result["celery"]["broker_connect_ok"] is True
    assert result["celery"]["worker_ping_ok"] is False
    assert result["celery"]["workers"] == []
