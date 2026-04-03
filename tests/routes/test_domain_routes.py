from __future__ import annotations

import app.features.domains.shared as domain_routes
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
                    "calendar_mode": "school_year",
                    "fiscal_year_start_month": 7,
                    "school_year_start_month": 8,
                    "school_year_end_month": 5,
                    "week_start": "monday",
                },
            }

    monkeypatch.setattr(domain_routes, "DomainTimePolicyService", _Svc)
    resp = client.get("/api/v1/domains/3/time-policy", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json["policy"]["calendar_mode"] == "school_year"


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
                "school_year_start_month": 8,
                "school_year_end_month": 5,
                "default_grain": "quarter",
                "allow_relative_ranges": True,
                "relative_map": {"this_quarter": "current_fiscal_quarter"},
                "semester": {
                    "labels": {"spring": "Spring", "fall": "Fall", "year_round": "Summer"},
                    "month_ranges": {"spring": [1, 5], "fall": [8, 12], "year_round": [6, 7]},
                    "indicator_columns": {"fall": "wt24.is_fall_term"},
                },
            }
        },
    )
    assert resp.status_code == 200
    assert resp.json["policy"]["default_grain"] == "quarter"


def test_domain_time_policy_put_service_error(client, auth_headers, monkeypatch):
    class _Svc:
        def update_policy(self, *, workspace_id: str, user_id: str, domain_id: int, policy_payload):
            raise ForgeError("policy.calendar_mode must be 'calendar', 'fiscal', or 'school_year'", status_code=400)

    monkeypatch.setattr(domain_routes, "DomainTimePolicyService", _Svc)
    resp = client.put(
        "/api/v1/domains/3/time-policy",
        headers=auth_headers,
        json={"policy": {"calendar_mode": "bad"}},
    )
    assert resp.status_code == 400
    assert "calendar_mode" in resp.json["error"]


def test_planner_rerank_policies_get_success(client, auth_headers, monkeypatch):
    class _Svc:
        def list_policies(self, *, workspace_id: str, user_id: str, base_domain_id, vertical_norm: str, include_inactive: bool):
            assert workspace_id == "ws-1"
            assert user_id == "user-1"
            assert base_domain_id == 9
            assert vertical_norm == "education"
            assert include_inactive is True
            return {
                "workspace_id": workspace_id,
                "vertical_norm": vertical_norm,
                "base_domain_id": base_domain_id,
                "domain_name": "Student Enrollment",
                "can_edit": True,
                "policies": [
                    {
                        "policy_key": "student_listing_school_literal",
                        "scope_type": "workspace_domain",
                        "policy_json": {"version": 1, "when_signals_all": ["student_listing"], "boost": 0.2},
                    }
                ],
            }

    monkeypatch.setattr(domain_routes, "PlannerRerankPolicyService", _Svc)
    resp = client.get(
        "/api/v1/domains/planner-rerank-policies?base_domain_id=9&vertical_norm=education&include_inactive=true",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json["policies"][0]["policy_key"] == "student_listing_school_literal"


def test_planner_rerank_policies_put_success(client, auth_headers, monkeypatch):
    class _Svc:
        def upsert_policy(self, *, workspace_id: str, actor_user_id: str, payload):
            assert workspace_id == "ws-1"
            assert actor_user_id == "user-1"
            return {
                "policy_id": 14,
                "policy_key": payload["policy_key"],
                "scope_type": payload["scope_type"],
                "scope_base_domain_id": payload["scope_base_domain_id"],
                "policy_json": dict(payload["policy_json"]),
            }

    monkeypatch.setattr(domain_routes, "PlannerRerankPolicyService", _Svc)
    resp = client.put(
        "/api/v1/domains/planner-rerank-policies",
        headers=auth_headers,
        json={
            "policy": {
                "policy_key": "student_listing_school_literal",
                "name": "Student listing school literal",
                "scope_type": "workspace_domain",
                "scope_base_domain_id": 9,
                "policy_json": {
                    "version": 1,
                    "when_signals_all": ["student_listing", "school_literal_present"],
                    "prefer_capabilities": ["STUDENT_IDENTITY", "SCHOOL_NAME"],
                    "boost": 0.2,
                    "penalty": 0.3,
                    "max_effect": 0.3,
                },
            }
        },
    )
    assert resp.status_code == 200
    assert resp.json["policy_id"] == 14
    assert resp.json["scope_base_domain_id"] == 9


def test_planner_rerank_policies_delete_success(client, auth_headers, monkeypatch):
    class _Svc:
        def delete_policy(self, *, workspace_id: str, actor_user_id: str, policy_id: int):
            assert workspace_id == "ws-1"
            assert actor_user_id == "user-1"
            assert policy_id == 14
            return {"deleted": True, "policy_id": 14}

    monkeypatch.setattr(domain_routes, "PlannerRerankPolicyService", _Svc)
    resp = client.delete(
        "/api/v1/domains/planner-rerank-policies/14",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json == {"deleted": True, "policy_id": 14}


def test_planner_rerank_policies_put_service_error(client, auth_headers, monkeypatch):
    class _Svc:
        def upsert_policy(self, *, workspace_id: str, actor_user_id: str, payload):
            raise ForgeError("workspace scope must match the active workspace", status_code=400)

    monkeypatch.setattr(domain_routes, "PlannerRerankPolicyService", _Svc)
    resp = client.put(
        "/api/v1/domains/planner-rerank-policies",
        headers=auth_headers,
        json={
            "policy": {
                "policy_key": "bad_rule",
                "name": "Bad Rule",
                "scope_type": "workspace",
                "scope_workspace_id": "ws-2",
                "policy_json": {
                    "version": 1,
                    "when_signals_all": ["student_listing"],
                    "prefer_capabilities": ["STUDENT_IDENTITY"],
                    "boost": 0.2,
                    "max_effect": 0.2,
                },
            }
        },
    )
    assert resp.status_code == 400
    assert "workspace scope" in resp.json["error"]


def test_planner_domain_capabilities_get_success(client, auth_headers, monkeypatch):
    class _Svc:
        def list_capabilities(self, *, workspace_id: str, user_id: str, base_domain_id: int, vertical_norm: str, include_inactive: bool):
            assert workspace_id == "ws-1"
            assert user_id == "user-1"
            assert base_domain_id == 9
            assert vertical_norm == "education"
            assert include_inactive is True
            return {
                "workspace_id": workspace_id,
                "base_domain_id": base_domain_id,
                "vertical_norm": vertical_norm,
                "domain_name": "Student Enrollment",
                "can_edit": True,
                "capabilities": [
                    {"capability_key": "SCHOOL_NAME", "scope_type": "workspace_domain", "is_inherited": False}
                ],
            }

    monkeypatch.setattr(domain_routes, "PlannerDomainCapabilityService", _Svc)
    resp = client.get(
        "/api/v1/domains/planner-domain-capabilities?base_domain_id=9&vertical_norm=education&include_inactive=true",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json["capabilities"][0]["capability_key"] == "SCHOOL_NAME"


def test_planner_domain_capabilities_put_success(client, auth_headers, monkeypatch):
    class _Svc:
        def upsert_capability(self, *, workspace_id: str, actor_user_id: str, payload):
            assert workspace_id == "ws-1"
            assert actor_user_id == "user-1"
            return {
                "capability_id": 12,
                "capability_key": payload["capability_key"],
                "base_domain_id": payload["base_domain_id"],
            }

    monkeypatch.setattr(domain_routes, "PlannerDomainCapabilityService", _Svc)
    resp = client.put(
        "/api/v1/domains/planner-domain-capabilities",
        headers=auth_headers,
        json={
            "capability": {
                "scope_type": "workspace_domain",
                "base_domain_id": 9,
                "capability_key": "SCHOOL_NAME",
                "support_level": "direct",
                "source_type": "semantic_concept",
            }
        },
    )
    assert resp.status_code == 200
    assert resp.json["capability_id"] == 12


def test_planner_domain_capabilities_delete_success(client, auth_headers, monkeypatch):
    class _Svc:
        def delete_capability(self, *, workspace_id: str, actor_user_id: str, capability_id: int):
            assert workspace_id == "ws-1"
            assert actor_user_id == "user-1"
            assert capability_id == 12
            return {"deleted": True, "capability_id": 12}

    monkeypatch.setattr(domain_routes, "PlannerDomainCapabilityService", _Svc)
    resp = client.delete(
        "/api/v1/domains/planner-domain-capabilities/12",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json == {"deleted": True, "capability_id": 12}


def test_planner_rerank_policy_candidates_get_success(client, auth_headers, monkeypatch):
    class _Svc:
        def list_candidates(self, *, workspace_id: str, review_status, vertical_norm):
            assert workspace_id == "ws-1"
            assert review_status == "pending"
            assert vertical_norm == "education"
            return {
                "workspace_id": workspace_id,
                "review_status": review_status,
                "vertical_norm": vertical_norm,
                "candidates": [
                    {"id": 4, "candidate_key": "candidate_1", "review_status": "pending"}
                ],
            }

    monkeypatch.setattr(domain_routes, "PlannerRerankPolicyCandidateService", _Svc)
    resp = client.get(
        "/api/v1/domains/planner-rerank-policy-candidates?review_status=pending&vertical_norm=education",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json["candidates"][0]["candidate_key"] == "candidate_1"


def test_planner_rerank_policy_candidates_post_success(client, auth_headers, monkeypatch):
    class _Svc:
        def create_candidate(self, *, workspace_id: str, payload):
            assert workspace_id == "ws-1"
            return {
                "candidate_id": 21,
                "candidate_key": payload["candidate_key"],
                "review_status": "pending",
            }

    monkeypatch.setattr(domain_routes, "PlannerRerankPolicyCandidateService", _Svc)
    resp = client.post(
        "/api/v1/domains/planner-rerank-policy-candidates",
        headers=auth_headers,
        json={
            "candidate": {
                "candidate_key": "candidate_1",
                "candidate_policy": {
                    "version": 1,
                    "when_signals_all": ["student_listing"],
                    "prefer_capabilities": ["STUDENT_IDENTITY"],
                    "boost": 0.2,
                    "max_effect": 0.2,
                },
            }
        },
    )
    assert resp.status_code == 201
    assert resp.json["candidate_id"] == 21


def test_planner_rerank_policy_candidates_put_success(client, auth_headers, monkeypatch):
    class _Svc:
        def create_candidate(self, *, workspace_id: str, payload):
            assert workspace_id == "ws-1"
            assert payload["id"] == 21
            return {
                "candidate_id": 21,
                "candidate_key": payload["candidate_key"],
                "review_status": "pending",
            }

    monkeypatch.setattr(domain_routes, "PlannerRerankPolicyCandidateService", _Svc)
    resp = client.put(
        "/api/v1/domains/planner-rerank-policy-candidates",
        headers=auth_headers,
        json={
            "candidate": {
                "id": 21,
                "candidate_key": "candidate_1",
                "candidate_policy": {
                    "version": 1,
                    "when_signals_all": ["student_listing"],
                    "prefer_capabilities": ["STUDENT_IDENTITY"],
                    "boost": 0.2,
                    "max_effect": 0.2,
                },
            }
        },
    )
    assert resp.status_code == 200
    assert resp.json["candidate_id"] == 21


def test_planner_rerank_policy_candidates_delete_success(client, auth_headers, monkeypatch):
    class _Svc:
        def delete_candidate(self, *, workspace_id: str, candidate_id: int):
            assert workspace_id == "ws-1"
            assert candidate_id == 21
            return {"deleted": True, "candidate_id": 21}

    monkeypatch.setattr(domain_routes, "PlannerRerankPolicyCandidateService", _Svc)
    resp = client.delete(
        "/api/v1/domains/planner-rerank-policy-candidates/21",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json == {"deleted": True, "candidate_id": 21}


def test_planner_rerank_policy_candidate_approve_success(client, auth_headers, monkeypatch):
    class _Svc:
        def approve_candidate(self, *, workspace_id: str, actor_user_id: str, candidate_id: int, payload):
            assert workspace_id == "ws-1"
            assert actor_user_id == "user-1"
            assert candidate_id == 21
            return {
                "candidate_id": candidate_id,
                "review_status": "approved",
                "approved_policy_id": 77,
            }

    monkeypatch.setattr(domain_routes, "PlannerRerankPolicyCandidateService", _Svc)
    resp = client.post(
        "/api/v1/domains/planner-rerank-policy-candidates/21/approve",
        headers=auth_headers,
        json={
            "approval": {
                "name": "Student listing school literal",
                "scope_type": "workspace_domain",
                "scope_base_domain_id": 9,
            }
        },
    )
    assert resp.status_code == 200
    assert resp.json["approved_policy_id"] == 77


def test_planner_rerank_policy_candidate_suggest_success(client, auth_headers, monkeypatch):
    class _Svc:
        def suggest_candidate(self, *, workspace_id: str, user_id: str, payload):
            assert workspace_id == "ws-1"
            assert user_id == "user-1"
            assert payload["expected_base_domain_id"] == 9
            return {
                "candidate": {
                    "candidate_id": 41,
                    "candidate_key": "student_school_enrollment_bias",
                    "review_status": "pending",
                },
                "prompt_signals": ["student_listing", "school_literal_present", "status_enrolled"],
                "expected_domain": {"base_domain_id": 9, "domain_name": "Student Enrollment"},
                "observed_domain": {"base_domain_id": 15, "domain_name": "Student Programs"},
            }

    monkeypatch.setattr(domain_routes, "PlannerRerankPolicyCandidateSuggestionService", _Svc)
    resp = client.post(
        "/api/v1/domains/planner-rerank-policy-candidates/suggest",
        headers=auth_headers,
        json={
            "suggestion": {
                "prompt": "Show me all the students enrolled at Barksdale Elementary",
                "expected_base_domain_id": 9,
                "observed_base_domain_id": 15,
                "vertical_norm": "generic",
            }
        },
    )
    assert resp.status_code == 201
    assert resp.json["candidate"]["candidate_id"] == 41


def test_planner_rerank_policy_candidate_suggest_returns_validation_error(client, auth_headers, monkeypatch):
    class _Svc:
        def suggest_candidate(self, *, workspace_id: str, user_id: str, payload):
            del workspace_id, user_id, payload
            raise ForgeError("AI helper could not derive a capability-grounded suggestion for this prompt.", status_code=422)

    monkeypatch.setattr(domain_routes, "PlannerRerankPolicyCandidateSuggestionService", _Svc)
    resp = client.post(
        "/api/v1/domains/planner-rerank-policy-candidates/suggest",
        headers=auth_headers,
        json={
            "suggestion": {
                "prompt": "How many days off are there in December?",
                "expected_base_domain_id": 6,
                "vertical_norm": "education",
            }
        },
    )
    assert resp.status_code == 422
    assert "capability-grounded suggestion" in resp.json["error"]
