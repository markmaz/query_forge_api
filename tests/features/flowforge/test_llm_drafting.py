import pytest

from app.exceptions.forge_error import ForgeError
from app.features.flowforge.llm_drafting import MatchingPolicyDraftGenerator
from app.features.flowforge.workflow_drafting import WorkflowGraphDraftGenerator, normalize_generated_workflow_graph


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


class _ShortcutWorkflowLLM:
    _model = "fake-workflow-model"

    def chat_json(self, **payload):
        return {
            "graph": {
                "nodes": [
                    {
                        "id": "start",
                        "type": "intake",
                        "label": "Jotform Intake Submitted",
                        "position": {"x": 120, "y": 140},
                        "data": {"source": "jotform-intake", "event": "intake_submitted"},
                    },
                    {
                        "id": "map_intake_to_schema",
                        "type": "map_transform",
                        "label": "Map Intake to Workflow Schema",
                        "position": {"x": 420, "y": 140},
                        "data": {
                            "field_mapping": [],
                            "template_fields": [],
                            "mappings": [{"from": "Email Address", "to": "values.patient.email"}],
                        },
                    },
                    {
                        "id": "match_therapists",
                        "type": "matching",
                        "label": "Match Therapists",
                        "position": {"x": 740, "y": 140},
                        "data": {"matching_policy_id": "", "resource_set_id": "", "top_k": 5},
                    },
                    {
                        "id": "notify_patient_matched",
                        "type": "notification",
                        "label": "Notify Patient of Therapist Options",
                        "position": {"x": 1020, "y": 140},
                        "data": {"communication_template_key": "flowforge.notification"},
                    },
                    {
                        "id": "no_match_notify",
                        "type": "notification",
                        "label": "Notify Ops: No Therapist Match Found",
                        "position": {"x": 1020, "y": 320},
                        "data": {"communication_template_key": "flowforge.notification"},
                    },
                    {"id": "end", "type": "end", "label": "End", "position": {"x": 1300, "y": 220}, "data": {}},
                ],
                "edges": [
                    {"id": "e_start_map", "source": "start", "target": "map_intake_to_schema"},
                    {"id": "e_map_match", "source": "map_intake_to_schema", "target": "match_therapists"},
                    {"id": "e_match_rank", "source": "match_therapists", "target": "notify_patient_matched", "branch": "matched"},
                    {"id": "e_notify_patient_end", "source": "notify_patient_matched", "target": "end"},
                    {"id": "e_match_no_match_notify", "source": "match_therapists", "target": "no_match_notify", "branch": "no_match"},
                    {"id": "e_no_match_end", "source": "no_match_notify", "target": "end"},
                ],
            },
            "plain_language_summary": "Shortcut summary.",
        }


class _WorkflowErrorLLM:
    _model = "bad-workflow-model"

    def chat_json(self, **payload):
        return {
            "error": {
                "message": "The model does not exist.",
                "type": "invalid_request_error",
                "code": "model_not_found",
            }
        }


class _WorkflowGraphlessLLM:
    _model = "graphless-workflow-model"

    def chat_json(self, **payload):
        return {"plain_language_summary": "I forgot the graph."}


class _RootNodesWorkflowLLM:
    _model = "root-nodes-workflow-model"

    def chat_json(self, **payload):
        return {
            "nodes": [
                {"id": "start", "type": "manual_start", "label": "Manual Start", "position": {"x": 120, "y": 140}, "data": {}},
                {"id": "done", "type": "end", "label": "Done", "position": {"x": 360, "y": 140}, "data": {}},
            ],
            "edges": [{"id": "start-done", "source": "start", "target": "done"}],
            "plain_language_summary": "Root-level graph.",
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


def test_workflow_graph_normalizer_repairs_llm_intake_aliases_and_branches():
    graph = {
        "nodes": [
            {
                "id": "start",
                "type": "intake",
                "label": "Jotform Intake Submitted",
                "position": {"x": 120, "y": 140},
                "data": {"integration_key": "jotform-intake", "event_key": "intake_submitted"},
            },
            {
                "id": "match_therapists",
                "type": "matching",
                "label": "Match Therapists",
                "position": {"x": 420, "y": 140},
                "data": {"matching_policy_id": 6, "resource_set_id": 2},
            },
            {
                "id": "iterate_candidates",
                "type": "iterator",
                "label": "Iterate Matched Therapists",
                "position": {"x": 720, "y": 140},
                "data": {},
            },
            {
                "id": "notify_admin_no_match",
                "type": "notification",
                "label": "Notify Admin: No Therapist Match",
                "position": {"x": 720, "y": 300},
                "data": {},
            },
            {
                "id": "decision_any_matches",
                "type": "decision",
                "label": "Any therapist matches?",
                "position": {"x": 1020, "y": 140},
                "data": {"outcomes": ["accepted", "declined"], "true_label": "Yes", "false_label": "No"},
            },
            {
                "id": "decision_task_outcome",
                "type": "decision",
                "label": "Therapist accepted?",
                "position": {"x": 1320, "y": 140},
                "data": {
                    "outcomes": ["accepted", "declined"],
                    "true_label": "Accept",
                    "false_label": "Decline/Timeout",
                },
            },
            {
                "id": "event_acceptance_created",
                "type": "event_capture",
                "label": "Create Acceptance Event",
                "position": {"x": 1620, "y": 40},
                "data": {},
            },
            {
                "id": "event_decline_or_timeout",
                "type": "event_capture",
                "label": "Create Decline/Timeout Event",
                "position": {"x": 1620, "y": 240},
                "data": {},
            },
        ],
        "edges": [
            {"id": "e_match_yes", "source": "match_therapists", "target": "iterate_candidates"},
            {"id": "e_match_no_match", "source": "match_therapists", "target": "notify_admin_no_match"},
            {"id": "e_any_yes", "source": "decision_any_matches", "target": "iterate_candidates"},
            {"id": "e_any_no", "source": "decision_any_matches", "target": "notify_admin_no_match"},
            {"id": "e_accept", "source": "decision_task_outcome", "target": "event_acceptance_created"},
            {"id": "e_decline_timeout", "source": "decision_task_outcome", "target": "event_decline_or_timeout"},
        ],
    }

    normalized = normalize_generated_workflow_graph(graph)
    nodes_by_id = {node["id"]: node for node in normalized["nodes"]}
    edges_by_id = {edge["id"]: edge for edge in normalized["edges"]}

    assert nodes_by_id["start"]["data"]["source"] == "jotform-intake"
    assert nodes_by_id["start"]["data"]["event"] == "intake_submitted"
    assert "integration_key" not in nodes_by_id["start"]["data"]
    assert "event_key" not in nodes_by_id["start"]["data"]

    assert edges_by_id["e_match_yes"]["branch"] == "matched"
    assert edges_by_id["e_match_no_match"]["branch"] == "no_match"
    assert nodes_by_id["decision_any_matches"]["data"]["outcomes"] == ["matched", "no_match"]
    assert edges_by_id["e_any_yes"]["branch"] == "matched"
    assert edges_by_id["e_any_no"]["branch"] == "no_match"
    assert nodes_by_id["decision_task_outcome"]["data"]["outcomes"] == ["accepted", "declined", "timed_out"]
    assert edges_by_id["e_accept"]["branch"] == "accepted"
    assert edges_by_id["e_decline_timeout"]["branches"] == ["declined", "timed_out"]


def test_workflow_graph_normalizer_preserves_manual_start_alias():
    normalized = normalize_generated_workflow_graph(
        {
            "nodes": [
                {
                    "id": "start",
                    "type": "manual",
                    "label": "Manual test run",
                    "position": {"x": 120, "y": 140},
                    "data": {},
                },
                {"id": "end", "type": "end", "label": "End", "position": {"x": 360, "y": 140}, "data": {}},
            ],
            "edges": [{"id": "start-end", "source": "start", "target": "end"}],
        }
    )

    assert normalized["nodes"][0]["type"] == "manual_start"
    assert normalized["nodes"][0]["data"] == {"mode": "manual"}


def test_workflow_graph_generator_repairs_resource_offer_shortcut_when_prompt_requires_acceptance_loop():
    prompt = (
        "I want a workflow that starts with an intake event from a jotform, maps the values in the form to a schema, "
        "passes those values into a matching policy where therapists are chosen based on the values from the form. "
        "Once a therapist is matched, they have 2 hours to either accept the new client, or decline and time out, "
        "then the next matching therapist is chosen. If no therapist is matched or accepts, an admin is notified."
    )

    result = WorkflowGraphDraftGenerator(llm_client=_ShortcutWorkflowLLM()).generate(
        prompt=prompt,
        current_graph={"nodes": [], "edges": []},
        draft_context={
            "matching_policies": [
                {
                    "id": 6,
                    "policy_key": "new-matching-policy-g5u6h7dew",
                    "resource_set_id": 2,
                    "published": True,
                }
            ],
            "resource_sets": [{"id": 2, "resource_set_key": "therapists-arpi965xt", "enabled": True}],
            "communication_templates": [
                {"template_key": "therapist1", "purpose": "human_task", "status": "active"},
                {"template_key": "client-accepted", "purpose": "notification", "status": "active"},
            ],
        },
        use_llm=True,
    )

    graph = result["graph"]
    nodes_by_id = {node["id"]: node for node in graph["nodes"]}
    edges_by_id = {edge["id"]: edge for edge in graph["edges"]}

    assert "notify_patient_matched" not in nodes_by_id
    assert nodes_by_id["map_intake_to_schema"]["data"]["field_mapping"] == [
        {"target": "values.patient.email", "source": "Email Address", "expose_to_templates": False}
    ]
    assert nodes_by_id["match_therapists"]["data"]["matching_policy_id"] == 6
    assert nodes_by_id["match_therapists"]["data"]["resource_set_id"] == 2
    assert nodes_by_id["therapist_response_task"]["data"]["timeout_minutes"] == 120
    assert nodes_by_id["therapist_response"]["data"]["outcomes"] == ["accepted", "declined", "timed_out", "no_match"]
    assert edges_by_id["e_match_matched_task"]["source"] == "match_therapists"
    assert edges_by_id["e_match_matched_task"]["target"] == "therapist_response_task"
    assert edges_by_id["e_match_matched_task"]["branch"] == "matched"
    assert edges_by_id["e_decision_accepted"]["branch"] == "accepted"
    assert edges_by_id["e_decision_declined"]["branch"] == "declined"
    assert edges_by_id["e_decision_timed_out"]["branch"] == "timed_out"
    assert edges_by_id["e_decision_no_match"]["branch"] == "no_match"
    assert edges_by_id["e_iterate_retry"]["target"] == "match_therapists"
    assert "Shortcut summary" not in result["plain_language_summary"]


def test_workflow_graph_generator_rejects_provider_error_payload():
    with pytest.raises(ForgeError) as exc:
        WorkflowGraphDraftGenerator(llm_client=_WorkflowErrorLLM()).generate(
            prompt="Create a manual notification workflow.",
            current_graph={"nodes": [{"id": "start", "type": "manual_start"}], "edges": []},
            use_llm=True,
        )

    assert exc.value.message == "Workflow AI provider returned an error"
    assert exc.value.details["provider_error"]["code"] == "model_not_found"


def test_workflow_graph_generator_rejects_graphless_llm_payload():
    with pytest.raises(ForgeError) as exc:
        WorkflowGraphDraftGenerator(llm_client=_WorkflowGraphlessLLM()).generate(
            prompt="Create a manual notification workflow.",
            current_graph={"nodes": [{"id": "start", "type": "manual_start"}], "edges": []},
            use_llm=True,
        )

    assert exc.value.message == "Workflow AI response did not include a workflow graph"


def test_workflow_graph_generator_accepts_root_level_nodes_payload():
    result = WorkflowGraphDraftGenerator(llm_client=_RootNodesWorkflowLLM()).generate(
        prompt="Create a manual notification workflow.",
        current_graph={"nodes": [], "edges": []},
        use_llm=True,
    )

    assert [node["type"] for node in result["graph"]["nodes"]] == ["manual_start", "end"]
    assert result["graph"]["edges"] == [{"id": "start-done", "source": "start", "target": "done"}]
