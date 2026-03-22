from __future__ import annotations

import app.routes.domain_routes as domain_routes
from app.exceptions.forge_error import ForgeError


def test_domains_get_success(client, auth_headers, monkeypatch):
    class _Svc:
        def list_user_domains(self, *, workspace_id: str, user_id: str):
            return [{"id": 1, "name": "Domain"}]

    monkeypatch.setattr(domain_routes, "UserDomainReadService", _Svc)

    resp = client.get("/api/v1/domains/", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json["rows"][0]["name"] == "Domain"


def test_domains_get_missing_workspace(client, auth_headers):
    headers = {k: v for k, v in auth_headers.items() if k.lower() != "x-workspace-id"}
    resp = client.get("/api/v1/domains/", headers=headers)
    assert resp.status_code == 400
    assert "Missing X-Workspace-Id" in resp.json["error"]


def test_domains_get_forbidden_workspace(client, monkeypatch):
    import app.decorators.security as security

    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": "user-1", "username": "user-1"},
    )

    def _deny_workspace_access(*, user_id: str, workspace_id: str) -> str:
        raise ForgeError("You do not have access to this workspace", status_code=403)

    monkeypatch.setattr(
        "app.decorators.security.workspace_access_service.assert_workspace_access",
        _deny_workspace_access,
    )

    resp = client.get(
        "/api/v1/domains/",
        headers={"Authorization": "Bearer token-1", "X-Workspace-Id": "ws-2"},
    )
    assert resp.status_code == 403
    assert "workspace" in resp.json["error"].lower()


def test_domains_get_allows_super_admin_without_workspace_membership(client, monkeypatch):
    import app.decorators.security as security
    import app.services.rbac_service as rbac_service

    monkeypatch.setattr(
        security.auth_service,
        "verify_token",
        lambda _token: {"sub": "admin-1", "username": "admin-1"},
    )

    def _deny_workspace_access(*, user_id: str, workspace_id: str) -> str:
        raise AssertionError("workspace membership should not be checked for super_admin")

    monkeypatch.setattr(
        "app.decorators.security.workspace_access_service.assert_workspace_access",
        _deny_workspace_access,
    )
    monkeypatch.setattr(
        rbac_service,
        "get_effective_roles",
        lambda user_id, workspace_id=None: {"super_admin"},
    )

    class _Svc:
        def list_user_domains(self, *, workspace_id: str, user_id: str):
            assert workspace_id == "ws-9"
            assert user_id == "admin-1"
            return [{"id": 1, "name": "Domain"}]

    monkeypatch.setattr(domain_routes, "UserDomainReadService", _Svc)

    resp = client.get(
        "/api/v1/domains/",
        headers={"Authorization": "Bearer token-1", "X-Workspace-Id": "ws-9"},
    )
    assert resp.status_code == 200
    assert resp.json["rows"][0]["name"] == "Domain"


def test_domains_get_service_error(client, auth_headers, monkeypatch):
    class _Svc:
        def list_user_domains(self, *, workspace_id: str, user_id: str):
            raise ForgeError("nope", status_code=418)

    monkeypatch.setattr(domain_routes, "UserDomainReadService", _Svc)

    resp = client.get("/api/v1/domains/", headers=auth_headers)
    assert resp.status_code == 418
    assert resp.json["error"] == "nope"


def test_domain_recommendations_generate_success(client, auth_headers, monkeypatch):
    class _Svc:
        def generate_recommendations(self, *, workspace_id, max_domains, max_tables, llm_id):
            assert workspace_id == "ws-1"
            assert max_domains == 8
            assert max_tables == 150
            assert llm_id == 12
            return {
                "workspace_id": workspace_id,
                "generated_at": "2026-03-19T21:00:00Z",
                "recommendations": [
                    {
                        "key": "student_demographics",
                        "name": "Student Demographics",
                        "description": "Core student context.",
                        "table_names": ["dim_student"],
                        "confidence": 0.91,
                        "rationale": ["student grain"],
                        "needs_review": False,
                    }
                ],
                "unassigned_tables": ["dim_subgroup"],
                "warnings": [],
            }

    monkeypatch.setattr(domain_routes, "DomainRecommendationService", _Svc)

    resp = client.post(
        "/api/v1/domains/recommendations/generate",
        headers=auth_headers,
        json={"max_domains": 8, "max_tables": 150, "llm_id": 12},
    )
    assert resp.status_code == 200
    assert resp.json["recommendations"][0]["name"] == "Student Demographics"
    assert resp.json["unassigned_tables"] == ["dim_subgroup"]


def test_domain_recommendations_generate_invalid_llm_id(client, auth_headers):
    resp = client.post(
        "/api/v1/domains/recommendations/generate",
        headers=auth_headers,
        json={"llm_id": "abc"},
    )
    assert resp.status_code == 400
    assert "llm_id must be an integer" in resp.json["error"]


def test_domain_recommendations_apply_success(client, auth_headers, monkeypatch):
    class _Svc:
        def apply_recommendations(
            self,
            *,
            workspace_id,
            user_id,
            recommendations,
            mode,
            column_name_policy,
        ):
            assert workspace_id == "ws-1"
            assert user_id == "user-1"
            assert mode == "create_only"
            assert column_name_policy == "DEDUP_PRIMARY_FIRST"
            assert recommendations[0]["name"] == "Student Demographics"
            return {
                "created_domains": [{"domain_id": 14, "name": "Student Demographics"}],
                "merged_domains": [],
                "assigned_tables": 3,
                "warnings": [],
            }

    monkeypatch.setattr(domain_routes, "DomainRecommendationService", _Svc)

    resp = client.post(
        "/api/v1/domains/recommendations/apply",
        headers=auth_headers,
        json={
            "mode": "create_only",
            "column_name_policy": "DEDUP_PRIMARY_FIRST",
            "recommendations": [
                {
                    "name": "Student Demographics",
                    "description": "Core student context.",
                    "table_names": ["dim_student", "dim_student_school", "fct_student_school_association"],
                }
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.json["created_domains"][0]["domain_id"] == 14
    assert resp.json["assigned_tables"] == 3


def test_domain_recommendations_apply_service_error(client, auth_headers, monkeypatch):
    class _Svc:
        def apply_recommendations(self, **kwargs):
            raise ForgeError("duplicate tables", status_code=400)

    monkeypatch.setattr(domain_routes, "DomainRecommendationService", _Svc)

    resp = client.post(
        "/api/v1/domains/recommendations/apply",
        headers=auth_headers,
        json={"recommendations": [{"name": "A", "table_names": ["t1"]}]},
    )
    assert resp.status_code == 400
    assert resp.json["error"] == "duplicate tables"


def test_domains_requires_auth(client):
    resp = client.get("/api/v1/domains/")
    assert resp.status_code == 403


def test_domains_invalid_token(client, invalid_auth_headers):
    resp = client.get("/api/v1/domains/", headers=invalid_auth_headers)
    assert resp.status_code == 401


def test_domain_profile_metrics_get_success(client, auth_headers, monkeypatch):
    class _Svc:
        def get_profile_metrics(self, *, workspace_id: str, user_id: str, domain_id: int):
            return {
                "domain_id": domain_id,
                "domain_name": "Sales Performance",
                "metrics": [{"metric_key": "total_net_amount", "agg": "sum"}],
                "has_profile": True,
                "can_edit": True,
            }

    monkeypatch.setattr(domain_routes, "DomainProfileMetricConfigService", _Svc)
    resp = client.get("/api/v1/domains/3/profile-metrics", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json["domain_id"] == 3
    assert resp.json["metrics"][0]["metric_key"] == "total_net_amount"


def test_domain_profile_metrics_put_success(client, auth_headers, monkeypatch):
    class _Svc:
        def update_profile_metrics(self, *, workspace_id: str, user_id: str, domain_id: int, metrics_payload):
            assert isinstance(metrics_payload, list)
            return {
                "domain_id": domain_id,
                "domain_name": "Sales Performance",
                "metrics": metrics_payload,
                "has_profile": True,
                "can_edit": True,
            }

    monkeypatch.setattr(domain_routes, "DomainProfileMetricConfigService", _Svc)
    resp = client.put(
        "/api/v1/domains/3/profile-metrics",
        headers=auth_headers,
        json={
            "metrics": [
                {
                    "metric_key": "total_net_amount",
                    "label": "Total Net Amount",
                    "kind": "numeric",
                    "agg": "sum",
                    "column_key": "wt180.net_amount",
                }
            ]
        },
    )
    assert resp.status_code == 200
    assert resp.json["metrics"][0]["agg"] == "sum"


def test_domain_profile_metrics_put_service_error(client, auth_headers, monkeypatch):
    class _Svc:
        def update_profile_metrics(self, *, workspace_id: str, user_id: str, domain_id: int, metrics_payload):
            raise ForgeError("'metrics' must be a list", status_code=400)

    monkeypatch.setattr(domain_routes, "DomainProfileMetricConfigService", _Svc)
    resp = client.put(
        "/api/v1/domains/3/profile-metrics",
        headers=auth_headers,
        json={"metrics": "bad"},
    )
    assert resp.status_code == 400
    assert "must be a list" in resp.json["error"]


def test_domain_time_policy_get_success(client, auth_headers, monkeypatch):
    class _Svc:
        def get_policy(self, *, workspace_id: str, user_id: str, domain_id: int):
            return {
                "domain_id": domain_id,
                "domain_name": "Sales Performance",
                "has_policy": True,
                "can_edit": True,
                "policy": {
                    "calendar_mode": "fiscal",
                    "fiscal_year_start_month": 7,
                    "week_start": "monday",
                },
            }

    monkeypatch.setattr(domain_routes, "DomainTimePolicyService", _Svc)
    resp = client.get("/api/v1/domains/3/time-policy", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json["policy"]["calendar_mode"] == "fiscal"


def test_domain_time_policy_put_success(client, auth_headers, monkeypatch):
    class _Svc:
        def update_policy(self, *, workspace_id: str, user_id: str, domain_id: int, policy_payload):
            return {
                "domain_id": domain_id,
                "domain_name": "Sales Performance",
                "has_policy": True,
                "can_edit": True,
                "policy": dict(policy_payload),
            }

    monkeypatch.setattr(domain_routes, "DomainTimePolicyService", _Svc)
    resp = client.put(
        "/api/v1/domains/3/time-policy",
        headers=auth_headers,
        json={
            "policy": {
                "calendar_mode": "fiscal",
                "fiscal_year_start_month": 7,
                "default_grain": "quarter",
                "allow_relative_ranges": True,
                "relative_map": {"this_quarter": "current_fiscal_quarter"},
            }
        },
    )
    assert resp.status_code == 200
    assert resp.json["policy"]["default_grain"] == "quarter"


def test_domain_time_policy_put_service_error(client, auth_headers, monkeypatch):
    class _Svc:
        def update_policy(self, *, workspace_id: str, user_id: str, domain_id: int, policy_payload):
            raise ForgeError("policy.calendar_mode must be 'calendar' or 'fiscal'", status_code=400)

    monkeypatch.setattr(domain_routes, "DomainTimePolicyService", _Svc)
    resp = client.put(
        "/api/v1/domains/3/time-policy",
        headers=auth_headers,
        json={"policy": {"calendar_mode": "bad"}},
    )
    assert resp.status_code == 400
    assert "calendar_mode" in resp.json["error"]
