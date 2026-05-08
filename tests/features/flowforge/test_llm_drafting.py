from app.features.flowforge.llm_drafting import MatchingPolicyDraftGenerator


class _FakeLLM:
    _model = "fake-flowforge-model"

    def __init__(self) -> None:
        self.calls = []

    def chat_json(self, **payload):
        self.calls.append(payload)
        return {
            "policy": {
                "version": 1,
                "eligibility": [{"field": "effective_status", "operator": "equals", "value": "active"}],
            },
            "plain_language_summary": "Require active resources.",
        }


class _AlternateShapeLLM:
    _model = "fake-flowforge-model"

    def chat_json(self, **payload):
        return {
            "policy": {
                "version": 1,
                "eligibility": {
                    "all": [
                        {"field": "status", "op": "eq", "value": "active"},
                        {
                            "field": "insurance_carriers",
                            "op": "contains_any",
                            "value_from": "inputs.patient_insurance_carriers",
                        },
                    ]
                },
                "scoring": {
                    "type": "points",
                    "rules": [
                        {
                            "name": "Specialty match",
                            "when": {
                                "field": "specialties",
                                "op": "contains_any",
                                "value_from": "inputs.requested_specialties",
                            },
                            "points": 50,
                        }
                    ],
                },
            },
            "plain_language_summary": "Require active therapists and match inputs.",
        }


def test_matching_policy_draft_generator_builds_local_heuristic_policy():
    result = MatchingPolicyDraftGenerator().generate(
        prompt="Prefer available resources with matching language.",
        resource_set_id=20,
        resource_fields=[{"key": "spoken_languages", "label": "Spoken Languages", "type": "array"}],
        intake_source={"integration_key": "jotform-intake", "event_key": "intake_submitted"},
        intake_fields=[{"path": "primaryLanguage", "label": "Primary Language", "type": "text"}],
    )

    policy = result["generated_policy"]
    assert policy["version"] == 1
    assert policy["resource_set_id"] == 20
    assert any(rule["id"] == "eligible-active" for rule in policy["eligibility"])
    language_rule = next(rule for rule in policy["scoring"] if rule["id"] == "score-language-match")
    assert language_rule["field"] == "spoken_languages"
    assert language_rule["context_field"] == "primaryLanguage"
    assert policy["inputs"]["intake_source"]["integration_key"] == "jotform-intake"
    assert policy["selection"]["strategy"] == "balanced_top_ranked"
    assert policy["selection"]["fairness"]["within_score_delta"] == 0
    assert result["draft_source"] == "heuristic"


def test_matching_policy_draft_generator_uses_llm_when_requested():
    llm = _FakeLLM()

    result = MatchingPolicyDraftGenerator(llm_client=llm).generate(
        prompt="Only active resources.",
        resource_set_id=20,
        resource_fields=["effective_status"],
        context_fields=[],
        intake_source={"integration_key": "jotform-intake", "event_key": "intake_submitted"},
        intake_fields=[{"path": "primaryLanguage", "label": "Primary Language", "type": "text"}],
        use_llm=True,
    )

    assert result["draft_source"] == "llm"
    assert result["model_name"] == "fake-flowforge-model"
    assert result["generated_policy"]["resource_set_id"] == 20
    assert result["generated_policy"]["inputs"]["intake_source"]["integration_key"] == "jotform-intake"
    assert "Only active resources." in llm.calls[0]["user_prompt"]
    assert "Allowed intake fields" in llm.calls[0]["user_prompt"]
    assert "primaryLanguage" in llm.calls[0]["user_prompt"]


def test_matching_policy_draft_generator_normalizes_llm_policy_shape():
    result = MatchingPolicyDraftGenerator(llm_client=_AlternateShapeLLM()).generate(
        prompt="Match active therapists by insurance and specialty.",
        resource_set_id=20,
        use_llm=True,
    )

    policy = result["generated_policy"]
    assert policy["eligibility"] == [
        {"id": "eligibility-1", "field": "status", "operator": "equals", "value": "active"},
        {
            "id": "eligibility-2",
            "field": "insurance_carriers",
            "operator": "contains_context",
            "context_field": "patient_insurance_carriers",
        },
    ]
    assert policy["scoring"] == [
        {
            "id": "scoring-1",
            "field": "specialties",
            "operator": "contains_context",
            "reason": "Specialty match",
            "context_field": "requested_specialties",
            "weight": 50,
        }
    ]
    assert policy["resource_set_id"] == 20
