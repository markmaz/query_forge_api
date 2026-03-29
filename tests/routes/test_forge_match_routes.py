from __future__ import annotations

import io

import app.routes.forge_match_routes as forge_match_routes


def _headers(monkeypatch):
    from app import factory
    from app.decorators import security
    from app.routes import request_helpers as _route_utils
    from app.services.workspace_inventory import workspace_context

    def _verify_token(_token):
        return {"sub": "user-1", "username": "user-1", "is_admin": True}

    def _allow_workspace_access(*, user_id, workspace_id):
        del user_id
        return workspace_id

    monkeypatch.setattr(security.auth_service, "verify_token", _verify_token)
    monkeypatch.setattr(factory.auth_service, "verify_token", _verify_token)
    monkeypatch.setattr(security.workspace_access_service, "assert_workspace_access", _allow_workspace_access)
    monkeypatch.setattr(_route_utils.workspace_access_service, "assert_workspace_access", _allow_workspace_access)
    monkeypatch.setattr(
        workspace_context.WorkspaceAccessService,
        "assert_workspace_access",
        lambda self, *, user_id, workspace_id: workspace_id,
    )
    return {
        "Authorization": "Bearer test-token",
        "X-Workspace-Id": "ws-1",
        "X-User-Id": "user-1",
    }


def test_forge_match_upload_route(client, monkeypatch):
    class _Svc:
        def upload_file(self, **kwargs):
            assert kwargs["workspace_id"] == "ws-1"
            return {
                "session_id": "sess-1",
                "workspace_id": "ws-1",
                "uploaded_filename": "mapping.csv",
                "file_type": "csv",
                "status": "uploaded",
                "sheet_count": 1,
                "source_record_count": 2,
                "source_preview": [],
            }

    monkeypatch.setattr(forge_match_routes, "ForgeMatchMappingService", _Svc)
    resp = client.post(
        "/api/v1/forge-match/upload",
        data={"file": (io.BytesIO(b"a,b\n1,2"), "mapping.csv")},
        content_type="multipart/form-data",
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 201
    assert resp.json["session_id"] == "sess-1"


def test_forge_match_list_sessions_route(client, monkeypatch):
    class _Svc:
        def list_sessions(self, **kwargs):
            assert kwargs["workspace_id"] == "ws-1"
            assert kwargs["status"] == "analyzed"
            return {
                "rows": [{"id": "sess-1", "status": "analyzed", "source_record_count": 12}],
                "total": 1,
                "page": 1,
                "page_size": 25,
            }

    monkeypatch.setattr(forge_match_routes, "ForgeMatchMappingService", _Svc)
    resp = client.get(
        "/api/v1/forge-match?status=analyzed&page=1&page_size=25",
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["total"] == 1
    assert resp.json["rows"][0]["id"] == "sess-1"


def test_forge_match_analyze_route(client, monkeypatch):
    class _Svc:
        def analyze_session(self, **kwargs):
            assert kwargs["session_id"] == "sess-1"
            assert kwargs["top_n"] == 8
            return {
                "session_id": "sess-1",
                "workspace_id": "ws-1",
                "status": "analyzed",
                "result_count": 1,
                "summary": {"total": 1},
                "mappings": [],
            }

    monkeypatch.setattr(forge_match_routes, "ForgeMatchMappingService", _Svc)
    resp = client.post(
        "/api/v1/forge-match/sess-1/analyze",
        json={"top_n": 8},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["status"] == "analyzed"


def test_forge_match_analyze_start_route(client, monkeypatch):
    called = {}

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        def ensure_connection(self, max_retries=0):
            assert max_retries == 0

    class _Celery:
        def connection_for_write(self):
            return _Conn()

        def connection(self):
            class _C:
                @staticmethod
                def as_uri():
                    return "redis://localhost:6379/0"

            return _C()

    class _Task:
        @staticmethod
        def apply_async(**kwargs):
            called["kwargs"] = kwargs

    class _Svc:
        def start_analyze_session_job(self, **kwargs):
            assert kwargs["session_id"] == "sess-1"
            return {
                "job_id": "job-1",
                "session_id": "sess-1",
                "workspace_id": "ws-1",
                "status": "queued",
                "source_total": 10,
            }

    monkeypatch.setattr(forge_match_routes, "analyze_forge_match_session_task", _Task)
    monkeypatch.setattr(forge_match_routes, "celery", _Celery())
    monkeypatch.setattr(forge_match_routes, "ForgeMatchMappingService", _Svc)
    resp = client.post(
        "/api/v1/forge-match/sess-1/analyze/start",
        json={"top_n": 8},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 202
    assert resp.json["job_id"] == "job-1"
    assert called["kwargs"]["task_id"] == "job-1"


def test_forge_match_analyze_start_route_enqueue_failure_returns_503(client, monkeypatch):
    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        def ensure_connection(self, max_retries=0):
            assert max_retries == 0

    class _Celery:
        def connection_for_write(self):
            return _Conn()

        def connection(self):
            class _C:
                @staticmethod
                def as_uri():
                    return "redis://localhost:6379/0"

            return _C()

    class _Task:
        @staticmethod
        def apply_async(**kwargs):
            del kwargs
            raise RuntimeError("broker down")

    class _Svc:
        def start_analyze_session_job(self, **kwargs):
            del kwargs
            return {
                "job_id": "job-1",
                "session_id": "sess-1",
                "workspace_id": "ws-1",
                "status": "queued",
                "source_total": 10,
            }

        def mark_enqueue_failed(self, **kwargs):
            assert kwargs["session_id"] == "sess-1"
            assert kwargs["job_id"] == "job-1"

    class _Health:
        def check_broker(self):
            return {"ok": False}

    monkeypatch.setattr(forge_match_routes, "analyze_forge_match_session_task", _Task)
    monkeypatch.setattr(forge_match_routes, "celery", _Celery())
    monkeypatch.setattr(forge_match_routes, "ForgeMatchMappingService", _Svc)
    monkeypatch.setattr(forge_match_routes, "AdminHealthService", _Health)
    resp = client.post(
        "/api/v1/forge-match/sess-1/analyze/start",
        json={"top_n": 8},
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 503
    assert resp.json["error"] == "forge_match analyze queue unavailable"
    assert resp.json["broker"]["ok"] is False


def test_forge_match_status_route(client, monkeypatch):
    class _Svc:
        def get_analysis_status(self, **kwargs):
            assert kwargs["job_id"] == "job-1"
            return {
                "id": "job-1",
                "job_id": "job-1",
                "session_id": "sess-1",
                "workspace_id": "ws-1",
                "status": "analyzing",
                "source_total": 10,
                "source_done": 3,
                "source_skipped": 0,
                "source_failed": 0,
                "progress_pct": 30.0,
                "cancel_requested": False,
            }

    monkeypatch.setattr(forge_match_routes, "ForgeMatchMappingService", _Svc)
    resp = client.get(
        "/api/v1/forge-match/status/job-1",
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["status"] == "analyzing"


def test_forge_match_cancel_route(client, monkeypatch):
    revoked = {}

    class _TaskResult:
        @staticmethod
        def revoke(**kwargs):
            revoked["kwargs"] = kwargs

    class _Task:
        @staticmethod
        def AsyncResult(_job_id):
            return _TaskResult()

    class _Svc:
        def cancel_analysis_job(self, **kwargs):
            assert kwargs["job_id"] == "job-1"
            return {
                "job_id": "job-1",
                "session_id": "sess-1",
                "canceled": True,
                "status": "canceled",
                "message": "Cancellation requested",
            }

    monkeypatch.setattr(forge_match_routes, "analyze_forge_match_session_task", _Task)
    monkeypatch.setattr(forge_match_routes, "ForgeMatchMappingService", _Svc)
    resp = client.post(
        "/api/v1/forge-match/cancel/job-1",
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["canceled"] is True
    assert revoked["kwargs"]["terminate"] is True


def test_forge_match_history_route(client, monkeypatch):
    class _Svc:
        def list_analysis_history(self, **kwargs):
            assert kwargs["workspace_id"] == "ws-1"
            return [
                {
                    "id": "job-1",
                    "job_id": "job-1",
                    "session_id": "sess-1",
                    "workspace_id": "ws-1",
                    "status": "analyzed",
                    "source_total": 10,
                    "source_done": 10,
                    "source_skipped": 0,
                    "source_failed": 0,
                    "progress_pct": 100.0,
                    "cancel_requested": False,
                }
            ]

    monkeypatch.setattr(forge_match_routes, "ForgeMatchMappingService", _Svc)
    resp = client.get(
        "/api/v1/forge-match/history?limit=20",
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert len(resp.json) == 1
    assert resp.json[0]["status"] == "analyzed"


def test_forge_match_patch_mappings_route(client, monkeypatch):
    class _Svc:
        def patch_mappings(self, **kwargs):
            assert kwargs["session_id"] == "sess-1"
            assert kwargs["reviewer_user_id"] == "user-1"
            return {"session_id": "sess-1", "workspace_id": "ws-1", "updated": 1, "rows": []}

    monkeypatch.setattr(forge_match_routes, "ForgeMatchMappingService", _Svc)
    resp = client.patch(
        "/api/v1/forge-match/sess-1/mappings",
        json={
            "updates": [
                {
                    "mapping_id": "map-1",
                    "action": "accept",
                }
            ]
        },
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["updated"] == 1


def test_forge_match_delete_session_route(client, monkeypatch):
    class _Svc:
        def delete_session(self, **kwargs):
            assert kwargs["session_id"] == "sess-1"
            assert kwargs["workspace_id"] == "ws-1"
            return {
                "session_id": "sess-1",
                "workspace_id": "ws-1",
                "deleted": True,
                "message": "ForgeMatch session deleted",
            }

    monkeypatch.setattr(forge_match_routes, "ForgeMatchMappingService", _Svc)
    resp = client.delete(
        "/api/v1/forge-match/sess-1",
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.json["deleted"] is True


def test_forge_match_export_route(client, monkeypatch):
    class _Svc:
        def export_session(self, **kwargs):
            assert kwargs["export_format"] == "csv"
            return (b"a,b\n1,2\n", "text/csv", "forge_match_sess-1.csv")

    monkeypatch.setattr(forge_match_routes, "ForgeMatchMappingService", _Svc)
    resp = client.get(
        "/api/v1/forge-match/sess-1/export?format=csv",
        headers=_headers(monkeypatch),
    )
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("text/csv")
