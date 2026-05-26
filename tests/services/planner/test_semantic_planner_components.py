from __future__ import annotations

import pytest

from app.services.planner.semantic_catalog_lookup_repository import SemanticCatalogLookupRepository
from app.services.planner import semantic_retrieval_service as retrieval_mod
from app.services.planner.planner_validation_service import PlannerValidationService
from app.services.planner.semantic_candidate_models import CompactSemanticPlan
from app.services.planner.semantic_plan_compiler import SemanticPlanCompiler
from app.services.planner.semantic_retrieval_service import SemanticRetrievalService
from app.services.feedback_learning.runtime_override_resolver import RuntimeOverrideResolver


class _Repo:
    def load_concepts(self):
        return [
            {"id": 1, "concept_key": "DOMAIN_SALES_PERFORMANCE", "name": "Sales Performance", "description": "", "semantic_type": "domain"},
            {"id": 2, "concept_key": "TOTAL_NET_AMOUNT", "name": "Total Net Amount", "description": "", "semantic_type": "metric"},
            {"id": 3, "concept_key": "TOTAL_GROSS_AMOUNT", "name": "Total Gross Amount", "description": "", "semantic_type": "metric"},
            {"id": 4, "concept_key": "QUOTA_REVENUE_AMOUNT", "name": "Quota Revenue Amount", "description": "", "semantic_type": "metric"},
            {"id": 5, "concept_key": "ACCOUNT_NAME", "name": "Account Name", "description": "", "semantic_type": "dimension"},
            {"id": 6, "concept_key": "ACCOUNT_ID", "name": "Account Id", "description": "", "semantic_type": "dimension"},
            {"id": 7, "concept_key": "TERRITORY_NAME", "name": "Territory Name", "description": "", "semantic_type": "dimension"},
            {"id": 8, "concept_key": "TERRITORY_ID", "name": "Territory Id", "description": "", "semantic_type": "dimension"},
            {"id": 9, "concept_key": "ACTIVE_TERRITORY_FLAG", "name": "Active Territory Flag", "description": "", "semantic_type": "filter"},
            {"id": 10, "concept_key": "TERRITORY_REGION", "name": "Territory Region", "description": "", "semantic_type": "filter"},
            {"id": 11, "concept_key": "ORDER_DATE", "name": "Order Date", "description": "", "semantic_type": "time_field"},
        ]

    def load_aliases(self):
        return [
            {"concept_key": "TOTAL_NET_AMOUNT", "alias_key": "sales", "weight": 1.0, "match_kind": "exact"},
            {"concept_key": "TOTAL_GROSS_AMOUNT", "alias_key": "sales", "weight": 1.0, "match_kind": "exact"},
            {"concept_key": "TOTAL_NET_AMOUNT", "alias_key": "revenue", "weight": 1.0, "match_kind": "contains"},
            {"concept_key": "QUOTA_REVENUE_AMOUNT", "alias_key": "revenue", "weight": 1.0, "match_kind": "contains"},
            {"concept_key": "ACCOUNT_NAME", "alias_key": "account", "weight": 1.0, "match_kind": "exact"},
            {"concept_key": "TERRITORY_NAME", "alias_key": "territory", "weight": 1.0, "match_kind": "exact"},
            {"concept_key": "ACTIVE_TERRITORY_FLAG", "alias_key": "active territories", "weight": 1.0, "match_kind": "contains"},
        ]

    def load_relationships(self):
        rows = []
        for child in (
            "TOTAL_NET_AMOUNT",
            "TOTAL_GROSS_AMOUNT",
            "QUOTA_REVENUE_AMOUNT",
            "ACCOUNT_NAME",
            "ACCOUNT_ID",
            "TERRITORY_NAME",
            "TERRITORY_ID",
            "ACTIVE_TERRITORY_FLAG",
            "TERRITORY_REGION",
            "ORDER_DATE",
        ):
            rows.append(
                {"parent_key": "DOMAIN_SALES_PERFORMANCE", "child_key": child, "relationship_type": "belongs_to_domain"}
            )
        rows.extend(
            [
                {"parent_key": "TOTAL_NET_AMOUNT", "child_key": "ORDER_DATE", "relationship_type": "default_time_field_for"},
                {"parent_key": "TOTAL_GROSS_AMOUNT", "child_key": "ORDER_DATE", "relationship_type": "default_time_field_for"},
            ]
        )
        return rows

    def load_concept_column_maps(self):
        return [
            {"semantic_concept_id": 5, "concept_key": "ACCOUNT_NAME", "model_column_id": 201, "relationship_kind": "primary", "weight": 1.0},
            {"semantic_concept_id": 6, "concept_key": "ACCOUNT_ID", "model_column_id": 202, "relationship_kind": "primary", "weight": 1.0},
            {"semantic_concept_id": 7, "concept_key": "TERRITORY_NAME", "model_column_id": 203, "relationship_kind": "primary", "weight": 1.0},
            {"semantic_concept_id": 8, "concept_key": "TERRITORY_ID", "model_column_id": 204, "relationship_kind": "primary", "weight": 1.0},
            {"semantic_concept_id": 9, "concept_key": "ACTIVE_TERRITORY_FLAG", "model_column_id": 205, "relationship_kind": "primary", "weight": 1.0},
            {"semantic_concept_id": 10, "concept_key": "TERRITORY_REGION", "model_column_id": 206, "relationship_kind": "primary", "weight": 1.0},
            {"semantic_concept_id": 11, "concept_key": "ORDER_DATE", "model_column_id": 207, "relationship_kind": "primary", "weight": 1.0},
        ]

    def load_suggestion_scores(self):
        return {"TOTAL_NET_AMOUNT": 5, "TOTAL_GROSS_AMOUNT": 5}

    def search_value_aliases(self, *, ngrams, semantic_concept_ids):
        del ngrams, semantic_concept_ids
        return []


def _capabilities() -> dict:
    return {
        "domain_metrics": [
            {"metric_key": "total_net_amount", "label": "Total Net Amount"},
            {"metric_key": "total_gross_amount", "label": "Total Gross Amount"},
            {"metric_key": "quota_revenue_amount", "label": "Quota Revenue Amount"},
        ],
        "user_metrics": [],
        "overlay_metrics": [],
        "dimensions": [
            {"column_key": "wt178.account_name", "column_name": "account_name", "label": "Account Name", "model_column_id": 201},
            {"column_key": "wt178.account_id", "column_name": "account_id", "label": "Account Id", "model_column_id": 202},
            {"column_key": "wt187.territory_name", "column_name": "territory_name", "label": "Territory Name", "model_column_id": 203},
            {"column_key": "wt187.territory_id", "column_name": "territory_id", "label": "Territory Id", "model_column_id": 204},
        ],
        "filter_columns": [
            {
                "column_key": "wt187.active_territory_flag",
                "column_name": "active_territory_flag",
                "label": "Active Territory Flag",
                "model_column_id": 205,
            },
            {"column_key": "wt187.territory_region", "column_name": "territory_region", "label": "Territory Region", "model_column_id": 206},
        ],
        "time_columns": [
            {"column_key": "wt179.order_date", "column_name": "order_date", "label": "Order Date", "model_column_id": 207},
        ],
    }


def _retrieve(prompt: str) -> object:
    svc = SemanticRetrievalService(repository=_Repo())
    return svc.retrieve(
        prompt=prompt,
        workspace_id="ws-1",
        base_domain_id=3,
        base_domain_name="Sales Performance",
        capabilities_compact=_capabilities(),
    )

def test_retrieve_returns_compact_candidate_payload_without_vertical_dimension() -> None:
    svc = SemanticRetrievalService(repository=_Repo())
    candidates = svc.retrieve(
        prompt="Show total net amount by territory",
        workspace_id="ws-1",
        base_domain_id=3,
        base_domain_name="Sales Performance",
        capabilities_compact=_capabilities(),
    )
    assert "vertical_norm" not in candidates.model_dump(mode="json")


def test_a_clear_aggregate_case() -> None:
    candidates = _retrieve("Show total net amount by territory")
    plan = CompactSemanticPlan.model_validate(
        {
            "base_domain_key": "domain_sales_performance",
            "intent": "aggregate",
            "metrics": ["total_net_amount"],
            "dimensions": ["territory_name"],
            "filters": [],
            "time": {"time_concept_key": None, "time_range": None, "time_grain": None, "start_date": None, "end_date": None},
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.95,
        }
    )
    validation = PlannerValidationService().validate(plan=plan, candidates=candidates)
    assert validation.errors == []
    assert validation.needs_clarification is False
    assert validation.normalized_plan.intent == "aggregate"
    assert validation.normalized_plan.metrics == ["TOTAL_NET_AMOUNT"]
    assert validation.normalized_plan.dimensions == ["TERRITORY_NAME"]


def test_b_ambiguous_metric_requires_clarification() -> None:
    candidates = _retrieve("Show total sales by territory")
    plan = CompactSemanticPlan.model_validate(
        {
            "base_domain_key": "domain_sales_performance",
            "intent": "aggregate",
            "metrics": ["sales"],
            "dimensions": ["territory_name"],
            "filters": [],
            "time": {"time_concept_key": None, "time_range": None, "time_grain": None, "start_date": None, "end_date": None},
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.62,
        }
    )
    validation = PlannerValidationService().validate(plan=plan, candidates=candidates)
    assert validation.errors
    assert validation.needs_clarification is True
    assert "or" in str(validation.clarification_question or "").lower()


def test_c_backfill_recovers_grouping_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retrieval_mod, "QF_PLAN_DOMAIN_COMPACT_MIN_CANDIDATE_SCORE", 0.99)
    candidates = _retrieve("Show total sales by account and territory")
    keys = {row.concept_key for row in candidates.dimension_candidates}
    assert "ACCOUNT_NAME" in keys
    assert "TERRITORY_NAME" in keys


def test_d_no_time_inference_when_not_requested() -> None:
    candidates = _retrieve("Show total net amount by account")
    plan = CompactSemanticPlan.model_validate(
        {
            "base_domain_key": "domain_sales_performance",
            "intent": "aggregate",
            "metrics": ["total_net_amount"],
            "dimensions": ["account_name"],
            "filters": [],
            "time": {"time_concept_key": None, "time_range": None, "time_grain": None, "start_date": None, "end_date": None},
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.91,
        }
    )
    validation = PlannerValidationService().validate(plan=plan, candidates=candidates)
    assert validation.errors == []

    compiled = SemanticPlanCompiler().compile(
        plan=validation.normalized_plan,
        candidates=candidates,
        trace_id="trace-1",
        workspace_id="ws-1",
        base_domain_id=3,
        base_domain_name="Sales Performance",
    )
    assert compiled.plan_json_v2["time"] == {}
    assert "vertical_norm" not in compiled.plan_json_v2


def test_e_filter_vs_dimension_separation() -> None:
    candidates = _retrieve("Show total net amount for active territories")
    dim_keys = {row.concept_key for row in candidates.dimension_candidates}
    filter_keys = {row.concept_key for row in candidates.filter_candidates}
    assert "ACTIVE_TERRITORY_FLAG" in filter_keys
    assert "ACTIVE_TERRITORY_FLAG" not in dim_keys

    plan = CompactSemanticPlan.model_validate(
        {
            "base_domain_key": "domain_sales_performance",
            "intent": "aggregate",
            "metrics": ["total_net_amount"],
            "dimensions": [],
            "filters": [{"field_concept_key": "active_territory_flag", "operator": "eq", "value": True}],
            "time": {"time_concept_key": None, "time_range": None, "time_grain": None, "start_date": None, "end_date": None},
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.86,
        }
    )
    validation = PlannerValidationService().validate(plan=plan, candidates=candidates)
    assert validation.errors == []
    assert validation.normalized_plan.dimensions == []
    assert validation.normalized_plan.filters[0].field_concept_key == "ACTIVE_TERRITORY_FLAG"


def test_f_invalid_model_output_rejected_with_clarification() -> None:
    candidates = _retrieve("Show total net amount by account")
    plan = CompactSemanticPlan.model_validate(
        {
            "base_domain_key": "domain_sales_performance",
            "intent": "aggregate",
            "metrics": ["total_net_amount"],
            "dimensions": ["NOT_A_REAL_CONCEPT"],
            "filters": [],
            "time": {"time_concept_key": None, "time_range": None, "time_grain": None, "start_date": None, "end_date": None},
            "needs_clarification": False,
            "clarification_question": None,
            "confidence": 0.88,
        }
    )
    validation = PlannerValidationService().validate(plan=plan, candidates=candidates)
    assert validation.errors
    assert validation.needs_clarification is True
    assert validation.clarification_question


class _RepoAliasWeightedExact(_Repo):
    def load_aliases(self):
        return [
            {"concept_key": "TOTAL_NET_AMOUNT", "alias_key": "sales", "weight": 10.0, "match_kind": "exact"},
            {"concept_key": "TOTAL_GROSS_AMOUNT", "alias_key": "sales", "weight": 1.0, "match_kind": "exact"},
            {"concept_key": "TOTAL_DISCOUNT_AMOUNT", "alias_key": "sales", "weight": 0.5, "match_kind": "contains"},
            {"concept_key": "ACCOUNT_NAME", "alias_key": "account", "weight": 1.0, "match_kind": "exact"},
            {"concept_key": "TERRITORY_NAME", "alias_key": "territory", "weight": 1.0, "match_kind": "exact"},
        ]


class _RepoAliasPrefixBeatsContains(_Repo):
    def load_aliases(self):
        return [
            {"concept_key": "TOTAL_NET_AMOUNT", "alias_key": "sale", "weight": 2.0, "match_kind": "prefix"},
            {"concept_key": "TOTAL_GROSS_AMOUNT", "alias_key": "sales", "weight": 3.0, "match_kind": "contains"},
            {"concept_key": "ACCOUNT_NAME", "alias_key": "account", "weight": 1.0, "match_kind": "exact"},
            {"concept_key": "TERRITORY_NAME", "alias_key": "territory", "weight": 1.0, "match_kind": "exact"},
        ]


class _RepoAliasRegex(_Repo):
    def load_aliases(self):
        return [
            {"concept_key": "TOTAL_NET_AMOUNT", "alias_key": r"\bsales\b", "weight": 1.5, "match_kind": "regex"},
            {"concept_key": "TOTAL_GROSS_AMOUNT", "alias_key": "revenue", "weight": 2.0, "match_kind": "contains"},
        ]


class _SemanticOverrideRepository:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def list_overrides(self, *, workspace_id=None, status=None, concept_key=None):
        out = list(self.rows)
        if workspace_id is None:
            out = [row for row in out if row.get("workspace_id") is None]
        else:
            out = [row for row in out if row.get("workspace_id") == workspace_id]
        if status is not None:
            out = [row for row in out if row.get("status") == status]
        if concept_key is not None:
            out = [row for row in out if row.get("concept_key") == concept_key]
        return out


class _DomainOverrideRepository:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def list_overrides(self, *, workspace_id=None, status=None, domain_key=None):
        out = list(self.rows)
        if workspace_id is None:
            out = [row for row in out if row.get("workspace_id") is None]
        else:
            out = [row for row in out if row.get("workspace_id") == workspace_id]
        if status is not None:
            out = [row for row in out if row.get("status") == status]
        if domain_key is not None:
            out = [row for row in out if row.get("domain_key") == domain_key]
        return out


def _retrieve_with_repo(prompt: str, repo: object) -> object:
    svc = SemanticRetrievalService(repository=repo)
    return svc.retrieve(
        prompt=prompt,
        workspace_id="ws-1",
        base_domain_id=3,
        base_domain_name="Sales Performance",
        capabilities_compact=_capabilities(),
    )


def _capabilities_without_account_dimension() -> dict:
    caps = _capabilities()
    caps["dimensions"] = [
        {"column_key": "wt187.territory_name", "column_name": "territory_name", "label": "Territory Name", "model_column_id": 203},
        {"column_key": "wt187.territory_id", "column_name": "territory_id", "label": "Territory Id", "model_column_id": 204},
    ]
    return caps


def test_g_lexical_hints_exact_with_weight_overrides_broad_bucket() -> None:
    candidates = _retrieve_with_repo("Show total sales by territory", _RepoAliasWeightedExact())
    assert candidates.lexical_hints.get("sales") == ["TOTAL_NET_AMOUNT"]


def test_h_lexical_hints_prefix_beats_contains() -> None:
    candidates = _retrieve_with_repo("Show total sales by territory", _RepoAliasPrefixBeatsContains())
    assert candidates.lexical_hints.get("sales") == ["TOTAL_NET_AMOUNT"]


def test_i_lexical_hints_regex_considered_when_present() -> None:
    candidates = _retrieve_with_repo("Show sales by territory", _RepoAliasRegex())
    assert candidates.lexical_hints.get("sales") == ["TOTAL_NET_AMOUNT"]


def test_i2_feedback_alias_override_can_break_metric_ties() -> None:
    resolver = RuntimeOverrideResolver(
        semantic_override_repository=_SemanticOverrideRepository(
            [
                {
                    "workspace_id": "ws-1",
                    "concept_key": "TOTAL_NET_AMOUNT",
                    "override_type": "add_alias",
                    "override_key": "sales",
                    "override_value_json": {
                        "alias_key": "sales",
                        "match_kind": "exact",
                        "weight": 12.0,
                    },
                    "status": "active",
                }
            ]
        ),
        domain_override_repository=_DomainOverrideRepository(),
    )
    repo = SemanticCatalogLookupRepository(
        sql=None,
        runtime_override_resolver=resolver,
    )
    svc = SemanticRetrievalService(repository=repo, runtime_override_resolver=resolver)

    candidates = svc.retrieve(
        prompt="Show total sales by territory",
        workspace_id="ws-1",
        base_domain_id=3,
        base_domain_name="Sales Performance",
        capabilities_compact=_capabilities(),
    )

    assert candidates.lexical_hints.get("sales") == ["TOTAL_NET_AMOUNT"]


def test_i3_feedback_domain_overrides_enrich_runtime_metadata() -> None:
    resolver = RuntimeOverrideResolver(
        semantic_override_repository=_SemanticOverrideRepository(),
        domain_override_repository=_DomainOverrideRepository(
            [
                {
                    "workspace_id": "ws-1",
                    "domain_key": "DOMAIN_SALES_PERFORMANCE",
                    "override_type": "add_domain_example_prompt",
                    "override_key": "show me sales by rep",
                    "override_value_json": {"prompt": "show me sales by rep"},
                    "status": "active",
                },
                {
                    "workspace_id": "ws-1",
                    "domain_key": "DOMAIN_SALES_PERFORMANCE",
                    "override_type": "add_domain_lexical_hint",
                    "override_key": "pipeline",
                    "override_value_json": {"hint": "pipeline"},
                    "status": "active",
                },
                {
                    "workspace_id": "ws-1",
                    "domain_key": "DOMAIN_SALES_PERFORMANCE",
                    "override_type": "add_ambiguity_note",
                    "override_key": "clarify gross vs net",
                    "override_value_json": {"note": "clarify gross vs net"},
                    "status": "active",
                },
            ]
        ),
    )
    svc = SemanticRetrievalService(repository=_Repo(), runtime_override_resolver=resolver)

    candidates = svc.retrieve(
        prompt="Show total sales by territory",
        workspace_id="ws-1",
        base_domain_id=3,
        base_domain_name="Sales Performance",
        capabilities_compact=_capabilities(),
    )

    assert candidates.metadata["feedback_domain_example_prompts"] == ["show me sales by rep"]
    assert candidates.metadata["feedback_ambiguity_notes"] == ["clarify gross vs net"]
    assert candidates.lexical_hints.get("pipeline") == ["DOMAIN_SALES_PERFORMANCE"]
    assert any("clarify gross vs net" in rule.lower() for rule in candidates.planning_rules)


def test_j_group_by_account_does_not_fall_back_to_account_type_filter_hint() -> None:
    svc = SemanticRetrievalService(repository=_Repo())
    candidates = svc.retrieve(
        prompt="Show total sales by account and territory",
        workspace_id="ws-1",
        base_domain_id=3,
        base_domain_name="Sales Performance",
        capabilities_compact=_capabilities_without_account_dimension(),
    )
    assert candidates.lexical_hints.get("account") != ["ACCOUNT_TYPE"]


class _FallbackSql:
    def __init__(self) -> None:
        self.calls = 0

    def execute_query_mappings(self, query: str, params=None):
        del params
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("Unknown column 'm.model_column_id' in 'field list'")
        assert "NULL AS model_column_id" in query
        return [
            {
                "semantic_concept_id": 5,
                "concept_key": "ACCOUNT_NAME",
                "workspace_column_id": 11,
                "model_column_id": None,
                "relationship_kind": "primary",
                "weight": 1.0,
            }
        ]


def test_k_repository_falls_back_when_model_column_id_is_missing() -> None:
    repo = SemanticCatalogLookupRepository(sql=_FallbackSql())
    rows = repo.load_concept_column_maps()

    assert rows == [
        {
            "semantic_concept_id": 5,
            "concept_key": "ACCOUNT_NAME",
            "workspace_column_id": 11,
            "model_column_id": None,
            "relationship_kind": "primary",
            "weight": 1.0,
        }
    ]


class _FatalRepo(_Repo):
    def load_relationships(self):
        raise RuntimeError("semantic relationship query failed")


def test_l_retrieval_falls_back_when_repository_fails() -> None:
    svc = SemanticRetrievalService(repository=_FatalRepo())
    candidates = svc.retrieve(
        prompt="Show total net amount by territory",
        workspace_id="ws-1",
        base_domain_id=3,
        base_domain_name="Sales Performance",
        capabilities_compact=_capabilities(),
    )

    assert candidates.metadata["semantic_source"] == "capabilities_fallback"
    assert candidates.base_domain_key == "SALES_PERFORMANCE"
    assert any(row.concept_key == "TERRITORY_NAME" for row in candidates.dimension_candidates)
