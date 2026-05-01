from __future__ import annotations

import app.features.feedback_learning.candidate_api as candidate_api
import app.features.feedback_learning.override_api as override_api


def _headers(monkeypatch):
    from flask import g

    from app import factory
    from app.decorators import rbac, security
    from app.routes import request_helpers as _route_utils
    from app.services.workspace_inventory import workspace_context

    def _verify_token(_token):
        return {"sub": "admin-1", "username": "admin-1"}

    def _allow_workspace_access(*, user_id, workspace_id):
        del user_id
        return workspace_id

    def _ensure_roles_loaded():
        g.effective_roles = {"ai:admin"}

    monkeypatch.setattr(security.auth_service, "verify_token", _verify_token)
    monkeypatch.setattr(factory.auth_service, "verify_token", _verify_token)
    monkeypatch.setattr(security.workspace_access_service, "assert_workspace_access", _allow_workspace_access)
    monkeypatch.setattr(_route_utils.workspace_access_service, "assert_workspace_access", _allow_workspace_access)
    monkeypatch.setattr(
        workspace_context.WorkspaceAccessService,
        "assert_workspace_access",
        lambda self, *, user_id, workspace_id: workspace_id,
    )
    monkeypatch.setattr(rbac, "workspace_has_feature", lambda workspace_id, feature_key: True)
    monkeypatch.setattr(rbac, "_ensure_roles_loaded", _ensure_roles_loaded)
    monkeypatch.setattr(rbac, "_is_super_admin", lambda: False)
    monkeypatch.setattr(rbac, "_is_workspace_admin", lambda: False)

    return {
        "Authorization": "Bearer test-token",
        "X-Workspace-Id": "ws-1",
        "X-User-Id": "spoofed-user",
    }


def test_feedback_learning_candidates_list_route_returns_page(client, monkeypatch):
    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def list_candidates(self, **filters):
            assert filters["workspace_id"] == "ws-1"
            return {
                "rows": [
                    {
                        "id": 88,
                        "governance_status": "pending",
                        "analysis_summary": {"failure_verdict": "domain_error"},
                        "source_feedback": {"prompt_feedback_id": 41},
                    }
                ],
                "total": 1,
                "page": 1,
                "page_size": 50,
            }

    monkeypatch.setattr(candidate_api, "CandidateReviewService", _Svc)

    response = client.get("/api/v1/feedback-learning/candidates", headers=_headers(monkeypatch))

    assert response.status_code == 200
    assert response.json["total"] == 1
    assert response.json["rows"][0]["id"] == 88


def test_feedback_learning_candidate_detail_route_returns_candidate_detail(client, monkeypatch):
    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def get_candidate_detail(self, *, candidate_id: int):
            assert candidate_id == 88
            return {
                "candidate": {"id": 88},
                "analysis_summary": {"failure_verdict": "domain_error"},
                "source_feedback": {"prompt_feedback_id": 41},
                "effective_target_key": "student_name",
            }

    monkeypatch.setattr(candidate_api, "CandidateReviewService", _Svc)

    response = client.get("/api/v1/feedback-learning/candidates/88", headers=_headers(monkeypatch))

    assert response.status_code == 200
    assert response.json["effective_target_key"] == "student_name"


def test_feedback_learning_candidate_approve_route_returns_result(client, monkeypatch):
    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def approve_candidate(self, *, candidate_id: int, reviewed_by: str):
            assert candidate_id == 88
            assert reviewed_by == "admin-1"
            return {
                "candidate": {"id": 88, "governance_status": "approved"},
                "candidate_status": "approved",
                "override": {"id": 21},
            }

    monkeypatch.setattr(candidate_api, "CandidateReviewService", _Svc)

    response = client.post("/api/v1/feedback-learning/candidates/88/approve", headers=_headers(monkeypatch))

    assert response.status_code == 200
    assert response.json["candidate_status"] == "approved"


def test_feedback_learning_candidate_approve_route_ignores_spoofed_user_header(client, monkeypatch):
    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def approve_candidate(self, *, candidate_id: int, reviewed_by: str):
            assert candidate_id == 88
            assert reviewed_by == "admin-1"
            return {
                "candidate": {"id": 88, "governance_status": "approved"},
                "candidate_status": "approved",
                "override": {"id": 21},
            }

    monkeypatch.setattr(candidate_api, "CandidateReviewService", _Svc)

    response = client.post("/api/v1/feedback-learning/candidates/88/approve", headers=_headers(monkeypatch))

    assert response.status_code == 200
    assert response.json["candidate_status"] == "approved"


def test_feedback_learning_candidate_reject_route_requires_reason(client, monkeypatch):
    response = client.post(
        "/api/v1/feedback-learning/candidates/88/reject",
        json={},
        headers=_headers(monkeypatch),
    )

    assert response.status_code == 400


def test_feedback_learning_bulk_reject_route_returns_summary(client, monkeypatch):
    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def bulk_reject(self, *, candidate_ids, reviewed_by: str, reason: str):
            assert candidate_ids == [88, 89]
            assert reviewed_by == "admin-1"
            assert reason == "Not safe"
            return {"processed": 2, "results": [{"candidate": {"id": 88}}, {"candidate": {"id": 89}}]}

    monkeypatch.setattr(candidate_api, "CandidateReviewService", _Svc)

    response = client.post(
        "/api/v1/feedback-learning/candidates/bulk-reject",
        json={"candidate_ids": [88, 89], "reason": "Not safe"},
        headers=_headers(monkeypatch),
    )

    assert response.status_code == 200
    assert response.json["processed"] == 2


def test_feedback_learning_semantic_override_list_route_returns_rows(client, monkeypatch):
    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def list_semantic_overrides(self, *, workspace_id: str):
            assert workspace_id == "ws-1"
            return [{"id": 21, "status": "active"}]

    monkeypatch.setattr(override_api, "CandidateReviewService", _Svc)

    response = client.get("/api/v1/feedback-learning/semantic-overrides", headers=_headers(monkeypatch))

    assert response.status_code == 200
    assert response.json["rows"][0]["id"] == 21


def test_feedback_learning_domain_override_deactivate_route_returns_result(client, monkeypatch):
    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def deactivate_domain_override(self, *, override_id: int, reviewed_by: str):
            assert override_id == 31
            assert reviewed_by == "admin-1"
            return {"id": 31, "status": "inactive"}

    monkeypatch.setattr(override_api, "CandidateReviewService", _Svc)

    response = client.post("/api/v1/feedback-learning/domain-overrides/31/deactivate", headers=_headers(monkeypatch))

    assert response.status_code == 200
    assert response.json["status"] == "inactive"


def test_feedback_learning_domain_override_deactivate_route_ignores_spoofed_user_header(client, monkeypatch):
    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def deactivate_domain_override(self, *, override_id: int, reviewed_by: str):
            assert override_id == 31
            assert reviewed_by == "admin-1"
            return {"id": 31, "status": "inactive"}

    monkeypatch.setattr(override_api, "CandidateReviewService", _Svc)

    response = client.post("/api/v1/feedback-learning/domain-overrides/31/deactivate", headers=_headers(monkeypatch))

    assert response.status_code == 200
    assert response.json["status"] == "inactive"


def test_feedback_learning_promotion_audit_list_route_returns_page(client, monkeypatch):
    class _Svc:
        def __init__(self, *args, **kwargs):
            pass

        def list_promotion_audits(self, **filters):
            return {"rows": [{"id": 7, "promotion_status": "succeeded"}], "total": 1, "limit": 50, "offset": 0}

    monkeypatch.setattr(override_api, "CandidateReviewService", _Svc)

    response = client.get("/api/v1/feedback-learning/promotion-audits", headers=_headers(monkeypatch))

    assert response.status_code == 200
    assert response.json["rows"][0]["id"] == 7
