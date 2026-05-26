from __future__ import annotations

from app.features.flowforge.matching import MatchingPolicyEngine


def test_matching_engine_validates_supported_policy_shape():
    policy = {
        "version": 1,
        "resource_set_id": "resources",
        "eligibility": [
            {
                "id": "active",
                "field": "effective_status",
                "operator": "equals",
                "value": "active",
                "reason": "Only active resources can receive offers.",
            }
        ],
        "scoring": [],
    }

    result = MatchingPolicyEngine().validate_policy(policy)

    assert result["valid"] is True
    assert result["errors"] == []


def test_matching_engine_rejects_unknown_operator_and_missing_field():
    policy = {
        "version": 1,
        "eligibility": [
            {"id": "bad-1", "operator": "regex", "value": ".*"},
        ],
    }

    result = MatchingPolicyEngine().validate_policy(policy)

    assert result["valid"] is False
    assert "eligibility[0].field is required." in result["errors"]
    assert "eligibility[0].operator 'regex' is not supported." in result["errors"]


def test_matching_engine_rejects_invalid_selection_strategy():
    policy = {
        "version": 1,
        "eligibility": [],
        "selection": {"strategy": "random"},
    }

    result = MatchingPolicyEngine().validate_policy(policy)

    assert result["valid"] is False
    assert "selection.strategy 'random' is not supported." in result["errors"]


def test_matching_engine_simulates_eligibility_scoring_and_ranking():
    policy = {
        "version": 1,
        "eligibility": [
            {
                "id": "active",
                "field": "effective_status",
                "operator": "equals",
                "value": "active",
                "reason": "Resource must be active.",
            },
            {
                "id": "language",
                "field": "languages",
                "operator": "contains_context",
                "context_field": "preferred_language",
                "reason": "Resource must support the preferred language.",
            },
        ],
        "scoring": [
            {
                "id": "capacity",
                "field": "capacity_available",
                "operator": "gt",
                "value": 0,
                "weight": 10,
                "reason": "Prefer resources with available capacity.",
            },
            {
                "id": "language-boost",
                "field": "languages",
                "operator": "contains_context",
                "context_field": "preferred_language",
                "weight": 15,
                "reason": "Boost language match.",
            },
        ],
    }
    resources = [
        {
            "source_record_key": "resource-1",
            "display_name": "Jane Resource",
            "effective_status": "active",
            "capacity_available": 2,
            "attributes": {"languages": ["Spanish"]},
        },
        {
            "source_record_key": "resource-2",
            "display_name": "Pat Resource",
            "effective_status": "on_hold",
            "capacity_available": 5,
            "attributes": {"languages": ["Spanish"]},
        },
        {
            "source_record_key": "resource-3",
            "display_name": "Sam Resource",
            "effective_status": "active",
            "capacity_available": 3,
            "attributes": {"languages": ["English"]},
        },
    ]

    result = MatchingPolicyEngine().simulate(policy=policy, resources=resources, context={"preferred_language": "Spanish"})

    assert result["valid"] is True
    assert result["selected_candidate"]["source_record_key"] == "resource-1"
    assert result["ranked_candidates"][0]["score"] == 25
    assert {row["source_record_key"] for row in result["excluded_candidates"]} == {"resource-2", "resource-3"}
    assert result["excluded_candidates"][0]["explanation"]


def test_matching_engine_balanced_selection_rotates_among_near_equal_candidates():
    policy = {
        "version": 1,
        "eligibility": [
            {
                "id": "active",
                "field": "effective_status",
                "operator": "equals",
                "value": "active",
                "reason": "Resource must be active.",
            }
        ],
        "scoring": [
            {
                "id": "qualified",
                "field": "qualified",
                "operator": "equals",
                "value": True,
                "weight": 20,
                "reason": "Resource is qualified.",
            },
            {
                "id": "preferred",
                "field": "preferred",
                "operator": "equals",
                "value": True,
                "weight": 2,
                "reason": "Resource is preferred.",
            },
        ],
        "selection": {
            "strategy": "balanced_top_ranked",
            "fairness": {
                "within_score_delta": 5,
                "penalize_active_offers": True,
                "prefer_least_recently_offered": True,
            },
        },
    }
    resources = [
        {
            "source_record_key": "resource-1",
            "display_name": "A Top But Busy",
            "effective_status": "active",
            "qualified": True,
            "preferred": True,
            "active_offer_count": 2,
            "last_offered_at": "2026-05-05T10:00:00Z",
        },
        {
            "source_record_key": "resource-2",
            "display_name": "B Near Equal Free",
            "effective_status": "active",
            "qualified": True,
            "preferred": False,
            "active_offer_count": 0,
            "last_offered_at": "2026-05-01T10:00:00Z",
        },
        {
            "source_record_key": "resource-3",
            "display_name": "C Near Equal Never Offered",
            "effective_status": "active",
            "qualified": True,
            "preferred": False,
            "active_offer_count": 0,
            "last_offered_at": None,
        },
    ]

    result = MatchingPolicyEngine().simulate(policy=policy, resources=resources, context={})

    assert result["selected_candidate"]["source_record_key"] == "resource-3"
    assert result["selected_candidate"]["selected"] is True
    assert [row["source_record_key"] for row in result["ranked_candidates"]] == ["resource-3", "resource-2", "resource-1"]


def test_matching_engine_balanced_selection_does_not_skip_clear_score_winner():
    policy = {
        "version": 1,
        "eligibility": [],
        "scoring": [
            {
                "id": "score",
                "field": "score_bucket",
                "operator": "equals",
                "value": "top",
                "weight": 100,
            }
        ],
        "selection": {
            "strategy": "balanced_top_ranked",
            "fairness": {
                "within_score_delta": 5,
                "penalize_active_offers": True,
                "prefer_least_recently_offered": True,
            },
        },
    }
    resources = [
        {
            "source_record_key": "resource-1",
            "display_name": "Clear Winner",
            "score_bucket": "top",
            "active_offer_count": 5,
            "last_offered_at": "2026-05-05T10:00:00Z",
        },
        {
            "source_record_key": "resource-2",
            "display_name": "Free But Lower Score",
            "score_bucket": "standard",
            "active_offer_count": 0,
            "last_offered_at": None,
        },
    ]

    result = MatchingPolicyEngine().simulate(policy=policy, resources=resources, context={})

    assert result["selected_candidate"]["source_record_key"] == "resource-1"
    assert [row["source_record_key"] for row in result["ranked_candidates"]] == ["resource-1", "resource-2"]


def test_matching_engine_returns_no_match_when_all_candidates_excluded():
    policy = {
        "version": 1,
        "eligibility": [
            {
                "id": "active",
                "field": "effective_status",
                "operator": "equals",
                "value": "active",
                "reason": "Resource must be active.",
            }
        ],
    }
    resources = [{"source_record_key": "resource-1", "effective_status": "on_hold"}]

    result = MatchingPolicyEngine().simulate(policy=policy, resources=resources, context={})

    assert result["valid"] is True
    assert result["selected_candidate"] is None
    assert result["no_match_reason"] == "no_eligible_candidates"
    assert result["excluded_candidates"][0]["exclusion_reasons"] == ["Resource must be active."]
