from __future__ import annotations

from app.services.semantic.plan import PlanService
from app.services.semantic.plan.models import LLMFilter, LLMPlanPayload, LLMSelectedColumn
from app.services.semantic.plan.sql_json_builder import SqlJsonBuilder
from app.services.semantic.plan.value_alias_applier import ValueAliasApplier
from app.services.semantic.plan.plan_validator import PlanValidator
from app.services.semantic.deterministic_matcher import DeterministicMatcher
from app.services.domain.planner_semantic_time_policy_service import PlannerSemanticTimePolicyService
from tests._support.fakes import FakeForgeQueryPort


def test_normalize_llm_payload_coerces_common_alternate_shapes() -> None:
    candidate_columns = [
        {"model_column_id": 383, "concept_key": "RACE", "table_name": "dim_student", "column_name": "race_array"},
        {"model_column_id": 381, "concept_key": "IS_HOMELESS", "table_name": "dim_student", "column_name": "is_homeless"},
        {"model_column_id": 286, "concept_key": "DISTRICT_NAME", "table_name": "dim_school", "column_name": "congressional_district"},
        {"model_column_id": 1080, "concept_key": "GRADE_LEVEL", "table_name": "fct_student_school_association", "column_name": "entry_grade_level"},
    ]
    payload = {
        "sql_json": {"select": {"value": ["dim_student.race_array"]}},
        "selected_columns": [383, 381],
        "filters": [
            {"model_column_id": 1080, "operator": "=", "value": "3"},
            {"model_column_id": 383, "operator": "=", "value": "black"},
        ],
        "join_plan": [{"left_table": "a", "right_table": "b"}],
        "confidence": 0.85,
        "notes": "single note",
    }

    out = SqlJsonBuilder.normalize_llm_payload(payload, candidate_columns=candidate_columns)

    assert out["selected_columns"] == [
        {"concept_key": "RACE", "model_column_id": 383},
        {"concept_key": "IS_HOMELESS", "model_column_id": 381},
    ]
    assert out["filters"] == [
        {"concept_key": "GRADE_LEVEL", "op": "=", "value": "3"},
        {"concept_key": "RACE", "op": "=", "value": "black"},
    ]
    assert out["join_plan"] == {"joins": [{"left_table": "a", "right_table": "b"}]}
    assert out["notes"] == ["single note"]
    assert out["confidence"] == 0.85


def test_normalize_llm_payload_can_map_filter_column_expression() -> None:
    candidate_columns = [
        {"model_column_id": 383, "concept_key": "RACE", "table_name": "dim_student", "column_name": "race_array"},
    ]
    payload = {
        "sql_json": {"where": {"conditions": []}},
        "selected_columns": [],
        "filters": [{"column": "dim_student.race_array", "operator": "=", "value": "black"}],
        "join_plan": {},
        "notes": [],
        "confidence": 2.2,
    }

    out = SqlJsonBuilder.normalize_llm_payload(payload, candidate_columns=candidate_columns)
    assert out["filters"] == [{"concept_key": "RACE", "op": "=", "value": "black"}]
    assert out["confidence"] == 1.0


def test_apply_value_aliases_to_llm_plan_rewrites_filter_and_sql_json() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "concept_key": "DISTRICT_NAME",
                "alias_value": "metro schools",
                "canonical_value": "Metro Schools District",
                "match_kind": "exact",
                "weight": 1.0,
                "vertical_norm": "education",
            }
        ]
    ]
    applier = ValueAliasApplier(sql=sql)
    llm_plan = {
        "sql_json": {
            "where": [
                {
                    "value": "district_name",
                    "op": "=",
                    "param": {"value": "metro schools"},
                }
            ]
        },
        "selected_columns": [],
        "filters": [{"concept_key": "DISTRICT_NAME", "op": "=", "value": "metro schools"}],
        "join_plan": {},
        "confidence": 0.8,
        "notes": [],
    }

    out = applier.apply(vertical_norm="education", llm_plan=llm_plan)

    assert out["filters"] == [
        {"concept_key": "DISTRICT_NAME", "op": "=", "value": "Metro Schools District"}
    ]
    assert out["sql_json"]["where"][0]["param"]["value"] == "Metro Schools District"
    assert "value_aliases_applied=1" in out["notes"]
    assert len(sql.query_mappings_calls) == 1
    assert "FROM semantic_value_alias va" in sql.query_mappings_calls[0].query


def test_ground_plan_builds_sql_json_from_grounded_candidates() -> None:
    candidate_columns = [
        {
            "model_column_id": 1115,
            "workspace_table_id": 501,
            "table_name": "fct_student_parent_association",
            "column_name": "k_student",
            "concept_key": "STUDENT_ID",
        },
        {
            "model_column_id": 2050,
            "workspace_table_id": 502,
            "table_name": "dim_student",
            "column_name": "birth_country",
            "concept_key": "BIRTH_COUNTRY",
        },
    ]
    concepts = [
        {"concept_key": "STUDENT_ID"},
        {"concept_key": "BIRTH_COUNTRY"},
    ]
    plan = LLMPlanPayload(
        sql_json={"from": "fct_student_parent_association"},
        selected_columns=[LLMSelectedColumn(concept_key="STUDENT_ID", model_column_id=1115)],
        filters=[LLMFilter(concept_key="BIRTH_COUNTRY", op="=", value="US")],
        join_plan={},
        confidence=0.8,
        notes=[],
    )

    out = SqlJsonBuilder.ground_plan(
        plan,
        candidate_columns,
        concepts,
        prompt="Show all kids not born in the US",
        domain_id=77,
    )

    sql_json = out["sql_json"]
    assert sql_json["domainId"] == 77
    assert sql_json["columns"][0]["field"]["modelColumnId"] == 1115
    assert sql_json["columns"][0]["field"]["columnName"] == "k_student"
    assert sql_json["columns"][0]["field"]["workspaceTableId"] == 501
    assert sql_json["filters"]["children"][0]["field"]["modelColumnId"] == 2050
    assert sql_json["filters"]["children"][0]["field"]["columnName"] == "birth_country"
    assert sql_json["filters"]["children"][0]["field"]["workspaceTableId"] == 502
    assert sql_json["meta"]["tool"] == "semantic_plan"


def test_ground_plan_drops_filters_without_mapped_columns() -> None:
    candidate_columns = [
        {
            "model_column_id": 1115,
            "table_name": "fct_student_parent_association",
            "column_name": "k_student",
            "concept_key": "STUDENT_ID",
        }
    ]
    concepts = [
        {"concept_key": "STUDENT_ID"},
        {"concept_key": "BIRTH_COUNTRY"},
    ]
    plan = LLMPlanPayload(
        sql_json={"from": "fct_student_parent_association"},
        selected_columns=[LLMSelectedColumn(concept_key="STUDENT_ID", model_column_id=1115)],
        filters=[LLMFilter(concept_key="BIRTH_COUNTRY", op="=", value="US")],
        join_plan={},
        confidence=0.8,
        notes=[],
    )

    out = SqlJsonBuilder.ground_plan(
        plan,
        candidate_columns,
        concepts,
        prompt="Show all kids not born in the US",
        domain_id=None,
    )

    assert out["filters"] == []
    assert out["sql_json"]["filters"] is None
    assert "grounding_removed=1" in out["notes"]


def test_apply_value_aliases_to_llm_plan_rewrites_sql_json_filter_tree_values() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "concept_key": "DISTRICT_NAME",
                "alias_value": "metro schools",
                "canonical_value": "Metro Schools District",
                "match_kind": "exact",
                "weight": 1.0,
                "vertical_norm": "education",
            }
        ]
    ]
    applier = ValueAliasApplier(sql=sql)
    llm_plan = {
        "sql_json": {
            "filters": {
                "type": "group",
                "id": "root",
                "match": "and",
                "children": [
                    {
                        "type": "condition",
                        "id": "c1",
                        "op": "equals",
                        "value": "metro schools",
                    }
                ],
            }
        },
        "selected_columns": [],
        "filters": [{"concept_key": "DISTRICT_NAME", "op": "=", "value": "metro schools"}],
        "join_plan": {},
        "confidence": 0.8,
        "notes": [],
    }

    out = applier.apply(vertical_norm="education", llm_plan=llm_plan)

    assert out["sql_json"]["filters"]["children"][0]["value"] == "Metro Schools District"


def test_plan_flow_keeps_birth_country_mapping_and_filter_column() -> None:
    class _Deterministic:
        def match(self, prompt):
            del prompt
            return {"matched": [], "unmatched_tokens": ["kids", "born", "us"]}

    class _ConceptRetrieval:
        def search(self, *, prompt, vertical_norm, max_concepts, deterministic_matches):
            del prompt, vertical_norm, max_concepts, deterministic_matches
            return {
                "query_text": "Show all kids not born in the US",
                "hits": [
                    {"concept_key": "BIRTH_COUNTRY", "score": 0.9, "source": "alias"},
                    {"concept_key": "STUDENT_ID", "score": 0.8, "source": "alias"},
                ],
            }

    class _ConceptToColumn:
        def map_concepts_to_columns(self, **kwargs):
            del kwargs
            return {
                "concepts": ["BIRTH_COUNTRY", "STUDENT_ID"],
                "mapped_columns": [
                    {
                        "model_column_id": 2050,
                        "workspace_table_id": 502,
                        "table_name": "dim_student",
                        "column_name": "birth_country",
                        "model_table_name": "dim_student",
                        "concept_key": "BIRTH_COUNTRY",
                        "weight": 1.0,
                        "final_score": 4.0,
                        "source": "m2m",
                    },
                    {
                        "model_column_id": 1115,
                        "workspace_table_id": 501,
                        "table_name": "fct_student_parent_association",
                        "column_name": "k_student",
                        "model_table_name": "fct_student_parent_association",
                        "concept_key": "STUDENT_ID",
                        "weight": 1.0,
                        "final_score": 2.0,
                        "source": "m2m",
                    },
                ],
                "candidate_model_column_ids": [2050, 1115],
                "ranked_candidates_by_concept": {
                    "BIRTH_COUNTRY": [{"model_column_id": 2050, "final_score": 4.0}],
                    "STUDENT_ID": [{"model_column_id": 1115, "final_score": 2.0}],
                },
            }

    class _ColumnVector:
        def search(self, **kwargs):
            del kwargs
            return {
                "filtered_to_candidate_count": 2,
                "hits": [
                    {
                        "model_column_id": 2050,
                        "workspace_table_id": 502,
                        "score": 0.91,
                        "table_name": "dim_student",
                        "column_name": "birth_country",
                        "concept_key": "BIRTH_COUNTRY",
                    },
                    {
                        "model_column_id": 1115,
                        "workspace_table_id": 501,
                        "score": 0.62,
                        "table_name": "fct_student_parent_association",
                        "column_name": "k_student",
                        "concept_key": "STUDENT_ID",
                    },
                ],
            }

    class _LLM:
        def chat_json(self, **kwargs):
            del kwargs
            return {
                "sql_json": {"from": "dim_student"},
                "selected_columns": [{"concept_key": "STUDENT_ID", "model_column_id": 1115}],
                "filters": [{"concept_key": "BIRTH_COUNTRY", "op": "!=", "value": "US"}],
                "join_plan": {},
                "confidence": 0.85,
                "notes": [],
            }

    svc = PlanService(
        sql=FakeForgeQueryPort(),
        deterministic=_Deterministic(),
        concept_retrieval=_ConceptRetrieval(),
        concept_to_column=_ConceptToColumn(),
        column_vector=_ColumnVector(),
        llm_client=_LLM(),
    )

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "prompt": "Show all kids not born in the US",
            "domain_id": 99,
            "debug": True,
        },
        include_llm=True,
    )

    mapped = out["concept_mapping"]["mapped_columns"]
    assert any(
        row["table_name"] == "dim_student" and row["column_name"] == "birth_country" for row in mapped
    )
    filter_field = out["llm_plan"]["sql_json"]["filters"]["children"][0]["field"]
    assert filter_field["columnName"] == "birth_country"
    assert filter_field["workspaceTableId"] == 502


def test_plan_flow_forces_canonical_district_filter_and_drops_locale_alias_filter() -> None:
    class _Deterministic:
        def match(self, prompt):
            del prompt
            return {"matched": [], "unmatched_tokens": ["metro", "schools"]}

    class _ConceptRetrieval:
        def search(self, *, prompt, vertical_norm, max_concepts, deterministic_matches):
            del prompt, vertical_norm, max_concepts, deterministic_matches
            return {
                "query_text": "metro schools",
                "hits": [
                    {"concept_key": "DISTRICT_NAME", "score": 0.9, "source": "alias"},
                    {"concept_key": "LOCALE", "score": 0.6, "source": "alias"},
                ],
            }

    class _ConceptToColumn:
        def map_concepts_to_columns(self, **kwargs):
            del kwargs
            return {
                "concepts": ["DISTRICT_NAME", "LOCALE"],
                "mapped_columns": [
                    {
                        "model_column_id": 286,
                        "workspace_table_id": 42,
                        "table_name": "dim_school",
                        "column_name": "district_name",
                        "concept_key": "DISTRICT_NAME",
                        "weight": 1.0,
                        "final_score": 4.2,
                    },
                    {
                        "model_column_id": 290,
                        "workspace_table_id": 42,
                        "table_name": "dim_school",
                        "column_name": "locale",
                        "concept_key": "LOCALE",
                        "weight": 1.0,
                        "final_score": 2.0,
                    },
                ],
                "candidate_model_column_ids": [286, 290],
                "ranked_candidates_by_concept": {},
            }

    class _ColumnVector:
        def search(self, **kwargs):
            del kwargs
            return {
                "filtered_to_candidate_count": 2,
                "hits": [
                    {
                        "model_column_id": 286,
                        "workspace_table_id": 42,
                        "table_name": "dim_school",
                        "column_name": "district_name",
                        "concept_key": "DISTRICT_NAME",
                        "score": 0.85,
                    },
                    {
                        "model_column_id": 290,
                        "workspace_table_id": 42,
                        "table_name": "dim_school",
                        "column_name": "locale",
                        "concept_key": "LOCALE",
                        "score": 0.8,
                    },
                ],
            }

    class _LLM:
        def chat_json(self, **kwargs):
            del kwargs
            return {
                "sql_json": {"from": "dim_school"},
                "selected_columns": [],
                "filters": [{"concept_key": "LOCALE", "op": "=", "value": "Metro"}],
                "join_plan": {},
                "confidence": 0.8,
                "notes": [],
            }

    class _ValueAliasResolver:
        def resolve(self, *, prompt, vertical_norm):
            del prompt, vertical_norm
            return [
                {
                    "concept_key": "DISTRICT_NAME",
                    "semantic_concept_id": 12,
                    "canonical_value": "Davidson County",
                    "matched_alias": "metro schools",
                    "matched_ngram": "metro schools",
                    "match_kind": "exact",
                    "weight": 1.0,
                },
                {
                    "concept_key": "LOCALE",
                    "semantic_concept_id": 13,
                    "canonical_value": "Metro",
                    "matched_alias": "metro",
                    "matched_ngram": "metro",
                    "match_kind": "contains",
                    "weight": 0.5,
                },
            ]

    class _DomainSelector:
        def choose_domain_id(self, **kwargs):
            del kwargs
            return {"domain_id": None, "source": "auto", "threshold_met": False, "domains": []}

    svc = PlanService(
        sql=FakeForgeQueryPort(),
        deterministic=_Deterministic(),
        concept_retrieval=_ConceptRetrieval(),
        concept_to_column=_ConceptToColumn(),
        column_vector=_ColumnVector(),
        llm_client=_LLM(),
        value_alias_resolver=_ValueAliasResolver(),
        domain_selector=_DomainSelector(),
    )

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "prompt": "show me metro schools",
        },
        include_llm=True,
    )

    filters = out["llm_plan"]["filters"]
    assert {"concept_key": "DISTRICT_NAME", "op": "=", "value": "Davidson County"} in filters
    assert all(str(row.get("concept_key") or "").upper() != "LOCALE" for row in filters)
    sql_filters = out["llm_plan"]["sql_json"]["filters"]["children"]
    assert len(sql_filters) == 1
    assert sql_filters[0]["field"]["columnName"] == "district_name"
    assert sql_filters[0]["value"] == "Davidson County"


def test_plan_suppresses_identifier_concepts_when_prompt_has_no_identifier_intent() -> None:
    class _Deterministic:
        def match(self, prompt):
            del prompt
            return {"matched": [], "unmatched_tokens": []}

    class _ConceptRetrieval:
        def search(self, *, prompt, vertical_norm, max_concepts, deterministic_matches):
            del prompt, vertical_norm, max_concepts, deterministic_matches
            return {
                "query_text": "show students in metro schools",
                "hits": [
                    {"concept_key": "DISTRICT_NAME", "score": 0.72, "source": "alias"},
                    {"concept_key": "LEA_ID", "score": 0.71, "source": "alias"},
                    {"concept_key": "SCHOOL_ID", "score": 0.70, "source": "alias"},
                    {"concept_key": "STUDENT_ID", "score": 0.69, "source": "alias"},
                    {"concept_key": "BIRTH_COUNTRY", "score": 0.68, "source": "alias"},
                ],
            }

    class _ConceptToColumn:
        def __init__(self):
            self.received_hits = []

        def map_concepts_to_columns(self, **kwargs):
            self.received_hits = list(kwargs.get("concept_hits") or [])
            return {
                "concepts": [str(hit.get("concept_key") or "").upper() for hit in self.received_hits],
                "mapped_columns": [],
                "candidate_model_column_ids": [],
                "ranked_candidates_by_concept": {},
            }

    class _ColumnVector:
        def search(self, **kwargs):
            del kwargs
            return {"filtered_to_candidate_count": 0, "hits": []}

    class _ValueAliasResolver:
        def resolve(self, *, prompt, vertical_norm):
            del prompt, vertical_norm
            return []

    class _DomainSelector:
        def choose_domain_id(self, **kwargs):
            del kwargs
            return {"domain_id": None, "source": "auto", "threshold_met": False, "domains": []}

    mapper = _ConceptToColumn()
    svc = PlanService(
        sql=FakeForgeQueryPort(),
        deterministic=_Deterministic(),
        concept_retrieval=_ConceptRetrieval(),
        concept_to_column=mapper,
        column_vector=_ColumnVector(),
        llm_client=object(),
        value_alias_resolver=_ValueAliasResolver(),
        domain_selector=_DomainSelector(),
    )

    svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "prompt": "show students in metro schools",
            "debug": True,
        },
        include_llm=False,
    )

    keys = [str(hit.get("concept_key") or "").upper() for hit in mapper.received_hits]
    assert "DISTRICT_NAME" in keys
    identifier_count = sum(1 for key in keys if key.endswith("_ID") or key.endswith("_CODE") or key.endswith("_SK"))
    assert identifier_count <= 1


def test_plan_keeps_identifier_concepts_when_prompt_requests_ids() -> None:
    class _Deterministic:
        def match(self, prompt):
            del prompt
            return {"matched": [], "unmatched_tokens": []}

    class _ConceptRetrieval:
        def search(self, *, prompt, vertical_norm, max_concepts, deterministic_matches):
            del prompt, vertical_norm, max_concepts, deterministic_matches
            return {
                "query_text": "show student id and school id",
                "hits": [
                    {"concept_key": "DISTRICT_NAME", "score": 0.72, "source": "alias"},
                    {"concept_key": "LEA_ID", "score": 0.71, "source": "alias"},
                    {"concept_key": "SCHOOL_ID", "score": 0.70, "source": "alias"},
                    {"concept_key": "STUDENT_ID", "score": 0.69, "source": "alias"},
                ],
            }

    class _ConceptToColumn:
        def __init__(self):
            self.received_hits = []

        def map_concepts_to_columns(self, **kwargs):
            self.received_hits = list(kwargs.get("concept_hits") or [])
            return {
                "concepts": [str(hit.get("concept_key") or "").upper() for hit in self.received_hits],
                "mapped_columns": [],
                "candidate_model_column_ids": [],
                "ranked_candidates_by_concept": {},
            }

    class _ColumnVector:
        def search(self, **kwargs):
            del kwargs
            return {"filtered_to_candidate_count": 0, "hits": []}

    class _ValueAliasResolver:
        def resolve(self, *, prompt, vertical_norm):
            del prompt, vertical_norm
            return []

    class _DomainSelector:
        def choose_domain_id(self, **kwargs):
            del kwargs
            return {"domain_id": None, "source": "auto", "threshold_met": False, "domains": []}

    mapper = _ConceptToColumn()
    svc = PlanService(
        sql=FakeForgeQueryPort(),
        deterministic=_Deterministic(),
        concept_retrieval=_ConceptRetrieval(),
        concept_to_column=mapper,
        column_vector=_ColumnVector(),
        llm_client=object(),
        value_alias_resolver=_ValueAliasResolver(),
        domain_selector=_DomainSelector(),
    )

    svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "prompt": "show student id and school id",
        },
        include_llm=False,
    )

    keys = [str(hit.get("concept_key") or "").upper() for hit in mapper.received_hits]
    assert "STUDENT_ID" in keys
    assert "SCHOOL_ID" in keys


def test_plan_black_kids_includes_race_from_lexical_alias_pass() -> None:
    class _Deterministic:
        def match(self, prompt):
            del prompt
            return {"matched": [], "unmatched_tokens": ["black", "kids"]}

    class _ConceptRetrieval:
        def search(self, *, prompt, vertical_norm, max_concepts, deterministic_matches):
            del prompt, vertical_norm, max_concepts, deterministic_matches
            return {
                "query_text": "black kids",
                "hits": [
                    {"concept_key": "CITY", "score": 0.71, "source": "vector"},
                    {"concept_key": "STUDENT_ID", "score": 0.69, "source": "vector"},
                ],
            }

    class _ConceptToColumn:
        def __init__(self):
            self.received_hits = []

        def map_concepts_to_columns(self, **kwargs):
            self.received_hits = list(kwargs.get("concept_hits") or [])
            return {
                "concepts": [str(hit.get("concept_key") or "").upper() for hit in self.received_hits],
                "mapped_columns": [],
                "candidate_model_column_ids": [],
                "ranked_candidates_by_concept": {},
                "warnings": [],
            }

    class _ColumnVector:
        def search(self, **kwargs):
            del kwargs
            return {"filtered_to_candidate_count": 0, "hits": []}

    class _ValueAliasResolver:
        def resolve(self, *, prompt, vertical_norm):
            del prompt, vertical_norm
            return []

    class _DomainSelector:
        def choose_domain_id(self, **kwargs):
            del kwargs
            return {"domain_id": None, "source": "auto", "threshold_met": False, "domains": []}

    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [],
        [{"concept_key": "RACE", "alias_key": "black", "match_kind": "contains", "weight": 1.0}],
        [],
        [
            {"concept_key": "CITY", "semantic_type": "attribute", "sub_type": None, "entity": "student", "description": "city", "is_identifier": 0},
            {"concept_key": "STUDENT_ID", "semantic_type": "identifier", "sub_type": "id", "entity": "student", "description": "student id", "is_identifier": 1},
            {"concept_key": "RACE", "semantic_type": "attribute", "sub_type": "demographic", "entity": "student", "description": "race", "is_identifier": 0},
        ],
    ]

    mapper = _ConceptToColumn()
    svc = PlanService(
        sql=sql,
        deterministic=_Deterministic(),
        concept_retrieval=_ConceptRetrieval(),
        concept_to_column=mapper,
        column_vector=_ColumnVector(),
        llm_client=object(),
        value_alias_resolver=_ValueAliasResolver(),
        domain_selector=_DomainSelector(),
    )

    svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "prompt": "black kids",
        },
        include_llm=False,
    )

    keys = [str(hit.get("concept_key") or "").upper() for hit in mapper.received_hits]
    assert "RACE" in keys


def test_plan_students_named_holden_prefers_student_name_mapping_and_filter() -> None:
    class _ConceptRetrieval:
        def search(self, *, prompt, vertical_norm, max_concepts, deterministic_matches):
            del prompt, vertical_norm, max_concepts, deterministic_matches
            return {
                "query_text": "Find all the students named Holden",
                "hits": [
                    {"concept_key": "LAST_NAME", "score": 0.8, "source": "vector"},
                    {"concept_key": "FIRST_NAME", "score": 0.75, "source": "vector"},
                    {"concept_key": "STUDENT_ID", "score": 0.7, "source": "vector"},
                ],
            }

    class _ConceptToColumn:
        def map_concepts_to_columns(self, **kwargs):
            assert kwargs.get("intent_entity") == "student"
            return {
                "concepts": ["LAST_NAME", "FIRST_NAME", "STUDENT_ID"],
                "mapped_columns": [
                    {
                        "model_column_id": 2001,
                        "workspace_table_id": 51,
                        "table_name": "dim_student",
                        "column_name": "last_name",
                        "concept_key": "LAST_NAME",
                        "base_weight": 1.0,
                        "effective_weight": 1.25,
                        "final_score": 3.0,
                    },
                    {
                        "model_column_id": 2002,
                        "workspace_table_id": 52,
                        "table_name": "dim_staff",
                        "column_name": "last_name",
                        "concept_key": "LAST_NAME",
                        "base_weight": 1.0,
                        "effective_weight": 0.65,
                        "final_score": 1.0,
                    },
                    {
                        "model_column_id": 2003,
                        "workspace_table_id": 51,
                        "table_name": "dim_student",
                        "column_name": "first_name",
                        "concept_key": "FIRST_NAME",
                        "base_weight": 1.0,
                        "effective_weight": 1.2,
                        "final_score": 2.8,
                    },
                    {
                        "model_column_id": 2004,
                        "workspace_table_id": 53,
                        "table_name": "fct_student_school_association",
                        "column_name": "k_student",
                        "concept_key": "STUDENT_ID",
                        "base_weight": 1.0,
                        "effective_weight": 1.1,
                        "final_score": 2.1,
                    },
                ],
                "candidate_model_column_ids": [2001, 2002, 2003, 2004],
                "ranked_candidates_by_concept": {},
                "warnings": [],
            }

    class _ColumnVector:
        def search(self, **kwargs):
            del kwargs
            return {
                "filtered_to_candidate_count": 4,
                "hits": [
                    {"model_column_id": 2004, "workspace_table_id": 53, "table_name": "fct_student_school_association", "column_name": "k_student", "concept_key": "STUDENT_ID", "score": 0.7},
                    {"model_column_id": 2001, "workspace_table_id": 51, "table_name": "dim_student", "column_name": "last_name", "concept_key": "LAST_NAME", "score": 0.69},
                    {"model_column_id": 2003, "workspace_table_id": 51, "table_name": "dim_student", "column_name": "first_name", "concept_key": "FIRST_NAME", "score": 0.68},
                ],
            }

    class _LLM:
        def chat_json(self, **kwargs):
            del kwargs
            return {
                "sql_json": {"from": "dim_student"},
                "selected_columns": [{"concept_key": "STUDENT_ID", "model_column_id": 2004}],
                "filters": [{"concept_key": "LAST_NAME", "op": "=", "value": "Holden"}],
                "join_plan": {},
                "confidence": 0.8,
                "notes": [],
            }

    class _ValueAliasResolver:
        def resolve(self, *, prompt, vertical_norm):
            del prompt, vertical_norm
            return []

    class _DomainSelector:
        def choose_domain_id(self, **kwargs):
            del kwargs
            return {"domain_id": None, "source": "auto", "threshold_met": False, "domains": []}

    svc = PlanService(
        sql=FakeForgeQueryPort(),
        deterministic=DeterministicMatcher(),
        concept_retrieval=_ConceptRetrieval(),
        concept_to_column=_ConceptToColumn(),
        column_vector=_ColumnVector(),
        llm_client=_LLM(),
        value_alias_resolver=_ValueAliasResolver(),
        domain_selector=_DomainSelector(),
    )

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "prompt": "Find all the students named Holden",
        },
        include_llm=True,
    )

    assert {"kind": "name", "value": "Holden", "source": "pattern:named"} in out["deterministic"]["extracted_values"]
    assert out["concept_mapping"]["mapped_columns"][0]["table_name"] == "dim_student"
    sql_children = out["llm_plan"]["sql_json"]["filters"]["children"]
    assert any(str(child.get("value") or "").lower() == "holden" for child in sql_children)
    assert len(out["llm_plan"]["sql_json"].get("columns") or []) >= 1


def test_plan_staff_named_holden_prefers_staff_name_filter() -> None:
    class _ConceptRetrieval:
        def search(self, *, prompt, vertical_norm, max_concepts, deterministic_matches):
            del prompt, vertical_norm, max_concepts, deterministic_matches
            return {
                "query_text": "Find all the staff named Holden",
                "hits": [
                    {"concept_key": "STAFF_LAST_NAME", "score": 0.86, "source": "vector"},
                    {"concept_key": "STAFF_FIRST_NAME", "score": 0.8, "source": "vector"},
                    {"concept_key": "STAFF_ID", "score": 0.75, "source": "vector"},
                ],
            }

    class _ConceptToColumn:
        def map_concepts_to_columns(self, **kwargs):
            assert kwargs.get("intent_entity") == "staff"
            return {
                "concepts": ["STAFF_LAST_NAME", "STAFF_FIRST_NAME", "STAFF_ID"],
                "mapped_columns": [
                    {"model_column_id": 3001, "workspace_table_id": 61, "table_name": "dim_staff", "column_name": "last_name", "concept_key": "STAFF_LAST_NAME", "base_weight": 1.0, "effective_weight": 1.25, "final_score": 3.1},
                    {"model_column_id": 3002, "workspace_table_id": 61, "table_name": "dim_staff", "column_name": "first_name", "concept_key": "STAFF_FIRST_NAME", "base_weight": 1.0, "effective_weight": 1.2, "final_score": 2.8},
                    {"model_column_id": 3003, "workspace_table_id": 62, "table_name": "fct_staff_assignment", "column_name": "k_staff", "concept_key": "STAFF_ID", "base_weight": 1.0, "effective_weight": 1.15, "final_score": 2.3},
                ],
                "candidate_model_column_ids": [3001, 3002, 3003],
                "ranked_candidates_by_concept": {},
                "warnings": [],
            }

    class _ColumnVector:
        def search(self, **kwargs):
            del kwargs
            return {
                "filtered_to_candidate_count": 3,
                "hits": [
                    {"model_column_id": 3003, "workspace_table_id": 62, "table_name": "fct_staff_assignment", "column_name": "k_staff", "concept_key": "STAFF_ID", "score": 0.76},
                    {"model_column_id": 3001, "workspace_table_id": 61, "table_name": "dim_staff", "column_name": "last_name", "concept_key": "STAFF_LAST_NAME", "score": 0.74},
                    {"model_column_id": 3002, "workspace_table_id": 61, "table_name": "dim_staff", "column_name": "first_name", "concept_key": "STAFF_FIRST_NAME", "score": 0.72},
                ],
            }

    class _LLM:
        def chat_json(self, **kwargs):
            del kwargs
            return {
                "sql_json": {},
                "selected_columns": [],
                "filters": [],
                "join_plan": {},
                "confidence": 0.6,
                "notes": [],
            }

    class _ValueAliasResolver:
        def resolve(self, *, prompt, vertical_norm):
            del prompt, vertical_norm
            return []

    class _DomainSelector:
        def choose_domain_id(self, **kwargs):
            del kwargs
            return {"domain_id": None, "source": "auto", "threshold_met": False, "domains": []}

    svc = PlanService(
        sql=FakeForgeQueryPort(),
        deterministic=DeterministicMatcher(),
        concept_retrieval=_ConceptRetrieval(),
        concept_to_column=_ConceptToColumn(),
        column_vector=_ColumnVector(),
        llm_client=_LLM(),
        value_alias_resolver=_ValueAliasResolver(),
        domain_selector=_DomainSelector(),
    )

    out = svc.plan(
        {"workspace_id": "ws-1", "vertical_norm": "education", "prompt": "Find all the staff named Holden"},
        include_llm=True,
    )

    filters = out["llm_plan"]["filters"]
    assert any(str(item.get("concept_key") or "").upper() == "STAFF_LAST_NAME" for item in filters)
    assert any(str(item.get("value") or "").lower() == "holden" for item in filters)
    columns = out["llm_plan"]["sql_json"].get("columns") or []
    assert len(columns) >= 1


def test_plan_validity_gate_injects_defaults_when_llm_returns_empty() -> None:
    class _ConceptRetrieval:
        def search(self, *, prompt, vertical_norm, max_concepts, deterministic_matches):
            del prompt, vertical_norm, max_concepts, deterministic_matches
            return {
                "query_text": "Find all the students named Holden",
                "hits": [
                    {"concept_key": "LAST_NAME", "score": 0.82, "source": "vector"},
                    {"concept_key": "FIRST_NAME", "score": 0.79, "source": "vector"},
                    {"concept_key": "STUDENT_ID", "score": 0.74, "source": "vector"},
                ],
            }

    class _ConceptToColumn:
        def map_concepts_to_columns(self, **kwargs):
            del kwargs
            return {
                "concepts": ["LAST_NAME", "FIRST_NAME", "STUDENT_ID"],
                "mapped_columns": [
                    {"model_column_id": 4001, "workspace_table_id": 71, "table_name": "dim_student", "column_name": "last_name", "concept_key": "LAST_NAME", "base_weight": 1.0, "effective_weight": 1.25, "final_score": 3.1},
                    {"model_column_id": 4002, "workspace_table_id": 71, "table_name": "dim_student", "column_name": "first_name", "concept_key": "FIRST_NAME", "base_weight": 1.0, "effective_weight": 1.2, "final_score": 2.9},
                    {"model_column_id": 4003, "workspace_table_id": 72, "table_name": "fct_student_school_association", "column_name": "k_student", "concept_key": "STUDENT_ID", "base_weight": 1.0, "effective_weight": 1.1, "final_score": 2.1},
                ],
                "candidate_model_column_ids": [4001, 4002, 4003],
                "ranked_candidates_by_concept": {},
                "warnings": [],
            }

    class _ColumnVector:
        def search(self, **kwargs):
            del kwargs
            return {
                "filtered_to_candidate_count": 3,
                "hits": [
                    {"model_column_id": 4003, "workspace_table_id": 72, "table_name": "fct_student_school_association", "column_name": "k_student", "concept_key": "STUDENT_ID", "score": 0.7},
                    {"model_column_id": 4001, "workspace_table_id": 71, "table_name": "dim_student", "column_name": "last_name", "concept_key": "LAST_NAME", "score": 0.69},
                    {"model_column_id": 4002, "workspace_table_id": 71, "table_name": "dim_student", "column_name": "first_name", "concept_key": "FIRST_NAME", "score": 0.68},
                ],
            }

    class _LLM:
        def chat_json(self, **kwargs):
            del kwargs
            return {
                "sql_json": {},
                "selected_columns": [],
                "filters": [],
                "join_plan": {},
                "confidence": 0.5,
                "notes": [],
            }

    class _ValueAliasResolver:
        def resolve(self, *, prompt, vertical_norm):
            del prompt, vertical_norm
            return []

    class _DomainSelector:
        def choose_domain_id(self, **kwargs):
            del kwargs
            return {"domain_id": None, "source": "auto", "threshold_met": False, "domains": []}

    svc = PlanService(
        sql=FakeForgeQueryPort(),
        deterministic=DeterministicMatcher(),
        concept_retrieval=_ConceptRetrieval(),
        concept_to_column=_ConceptToColumn(),
        column_vector=_ColumnVector(),
        llm_client=_LLM(),
        value_alias_resolver=_ValueAliasResolver(),
        domain_selector=_DomainSelector(),
    )

    out = svc.plan(
        {"workspace_id": "ws-1", "vertical_norm": "education", "prompt": "Find all the students named Holden"},
        include_llm=True,
    )

    assert out["llm_plan"]["selected_columns"]
    assert any(str(item.get("value") or "").lower() == "holden" for item in out["llm_plan"]["filters"])
    assert out["llm_plan"]["sql_json"].get("columns")
    assert out["llm_plan"]["sql_json"].get("filters")


def test_plan_el_subgroup_injects_is_el_filter_and_keeps_sql_json() -> None:
    class _SemanticExtractor:
        def extract(self, prompt):
            return {
                "normalized_text": prompt,
                "by_label": {"SUBGROUP": ["EL students"]},
                "slots": {},
                "ents": [{"label": "SUBGROUP", "text": "EL students", "start": 9, "end": 20}],
                "warnings": [],
                "model": {"path": "models/tier2_ner_v1_stable", "loaded": True},
            }

    class _ConceptRetrieval:
        def search(self, *, prompt, vertical_norm, max_concepts, deterministic_matches):
            del prompt, vertical_norm, max_concepts, deterministic_matches
            return {
                "query_text": "How many EL students were chronically absent last year?",
                "hits": [
                    {"concept_key": "STUDENT_ID", "score": 0.8, "source": "vector"},
                    {"concept_key": "IS_EL", "score": 0.76, "source": "vector"},
                ],
            }

    class _ConceptToColumn:
        def map_concepts_to_columns(self, **kwargs):
            del kwargs
            return {
                "concepts": ["STUDENT_ID", "IS_EL"],
                "mapped_columns": [
                    {"model_column_id": 6101, "workspace_table_id": 201, "table_name": "dim_student", "column_name": "k_student", "concept_key": "STUDENT_ID", "base_weight": 1.0, "effective_weight": 1.3, "final_score": 3.0},
                    {"model_column_id": 6102, "workspace_table_id": 201, "table_name": "dim_student", "column_name": "is_el", "concept_key": "IS_EL", "base_weight": 1.0, "effective_weight": 1.4, "final_score": 3.4},
                ],
                "candidate_model_column_ids": [6101, 6102],
                "ranked_candidates_by_concept": {},
                "warnings": [],
            }

    class _ColumnVector:
        def search(self, **kwargs):
            del kwargs
            return {
                "filtered_to_candidate_count": 2,
                "hits": [
                    {"model_column_id": 6102, "workspace_table_id": 201, "table_name": "dim_student", "column_name": "is_el", "concept_key": "IS_EL", "score": 0.82},
                    {"model_column_id": 6101, "workspace_table_id": 201, "table_name": "dim_student", "column_name": "k_student", "concept_key": "STUDENT_ID", "score": 0.8},
                ],
            }

    class _LLM:
        def chat_json(self, **kwargs):
            del kwargs
            return {
                "sql_json": {"from": "dim_student"},
                "selected_columns": [{"concept_key": "STUDENT_ID", "model_column_id": 6101}],
                "filters": [],
                "join_plan": {"primary_table": "dim_student"},
                "confidence": 0.7,
                "notes": [],
            }

    class _ValueAliasResolver:
        def resolve(self, *, prompt, vertical_norm):
            del prompt, vertical_norm
            return []

    class _DomainSelector:
        def choose_domain_id(self, **kwargs):
            del kwargs
            return {"domain_id": None, "source": "auto", "threshold_met": False, "domains": []}

    svc = PlanService(
        sql=FakeForgeQueryPort(),
        deterministic=DeterministicMatcher(),
        concept_retrieval=_ConceptRetrieval(),
        concept_to_column=_ConceptToColumn(),
        column_vector=_ColumnVector(),
        llm_client=_LLM(),
        value_alias_resolver=_ValueAliasResolver(),
        domain_selector=_DomainSelector(),
        semantic_extractor=_SemanticExtractor(),
    )

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "prompt": "How many EL students were chronically absent last year?",
        },
        include_llm=True,
    )

    filters = out["llm_plan"]["filters"]
    assert any(str(item.get("concept_key") or "").upper() == "IS_EL" for item in filters)

    sql_filters = (out["llm_plan"]["sql_json"].get("filters") or {}).get("children") or []
    assert any(
        child["field"]["columnName"] == "is_el"
        and child.get("op") in {"equals", "="}
        and child.get("value") is True
        for child in sql_filters
    )
    assert out["llm_plan"]["sql_json"] != {}
    assert "plan_invalid_empty_or_unfiltered" not in out["debug"]["warnings"]


def test_plan_injects_student_first_last_and_school_filter_for_school_phrase_prompt() -> None:
    class _ConceptRetrieval:
        def search(self, *, prompt, vertical_norm, max_concepts, deterministic_matches):
            del prompt, vertical_norm, max_concepts, deterministic_matches
            return {
                "query_text": "Give me all the first and last names of all students at the Clarksville Elementary School",
                "hits": [
                    {"concept_key": "FIRST_NAME", "score": 0.8, "source": "vector"},
                    {"concept_key": "LAST_NAME", "score": 0.79, "source": "vector"},
                    {"concept_key": "SCHOOL_NAME", "score": 0.74, "source": "vector"},
                    {"concept_key": "STAFF_FIRST_NAME", "score": 0.73, "source": "vector"},
                ],
            }

    class _ConceptToColumn:
        def map_concepts_to_columns(self, **kwargs):
            assert kwargs.get("intent_entity") == "student"
            return {
                "concepts": ["FIRST_NAME", "LAST_NAME", "SCHOOL_NAME", "STAFF_FIRST_NAME"],
                "mapped_columns": [
                    {"model_column_id": 5001, "workspace_table_id": 81, "table_name": "dim_student", "column_name": "first_name", "concept_key": "FIRST_NAME", "base_weight": 1.0, "effective_weight": 1.3, "final_score": 3.4},
                    {"model_column_id": 5002, "workspace_table_id": 81, "table_name": "dim_student", "column_name": "last_name", "concept_key": "LAST_NAME", "base_weight": 1.0, "effective_weight": 1.3, "final_score": 3.3},
                    {"model_column_id": 5003, "workspace_table_id": 82, "table_name": "dim_school", "column_name": "school_name", "concept_key": "SCHOOL_NAME", "base_weight": 1.0, "effective_weight": 1.2, "final_score": 3.0},
                    {"model_column_id": 5004, "workspace_table_id": 83, "table_name": "dim_staff", "column_name": "first_name", "concept_key": "STAFF_FIRST_NAME", "base_weight": 1.0, "effective_weight": 0.5, "final_score": 1.0},
                ],
                "candidate_model_column_ids": [5001, 5002, 5003, 5004],
                "ranked_candidates_by_concept": {},
                "warnings": [],
            }

    class _ColumnVector:
        def search(self, **kwargs):
            del kwargs
            return {"filtered_to_candidate_count": 0, "hits": []}

    class _LLM:
        def chat_json(self, **kwargs):
            del kwargs
            return {
                "sql_json": {},
                "selected_columns": [],
                "filters": [],
                "join_plan": {},
                "confidence": 0.5,
                "notes": [],
            }

    class _ValueAliasResolver:
        def resolve(self, *, prompt, vertical_norm):
            del prompt, vertical_norm
            return []

    class _DomainSelector:
        def choose_domain_id(self, **kwargs):
            del kwargs
            return {"domain_id": None, "source": "auto", "threshold_met": False, "domains": []}

    svc = PlanService(
        sql=FakeForgeQueryPort(),
        deterministic=DeterministicMatcher(),
        concept_retrieval=_ConceptRetrieval(),
        concept_to_column=_ConceptToColumn(),
        column_vector=_ColumnVector(),
        llm_client=_LLM(),
        value_alias_resolver=_ValueAliasResolver(),
        domain_selector=_DomainSelector(),
    )

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "prompt": "Give me all the first and last names of all students at the Clarksville Elementary School",
        },
        include_llm=True,
    )

    extracted = out["deterministic"].get("extracted_values") or []
    assert {
        "kind": "school_name",
        "value": "Clarksville Elementary School",
        "source": "pattern:at_school",
    } in extracted

    selected = out["llm_plan"]["selected_columns"]
    selected_keys = {str(item.get("concept_key") or "").upper() for item in selected}
    assert "FIRST_NAME" in selected_keys
    assert "LAST_NAME" in selected_keys

    sql_json = out["llm_plan"]["sql_json"]
    column_names = [col["field"]["columnName"] for col in sql_json.get("columns") or []]
    assert "first_name" in column_names
    assert "last_name" in column_names

    filter_children = (sql_json.get("filters") or {}).get("children") or []
    assert any(
        child["field"]["columnName"] == "school_name"
        and str(child.get("value") or "").lower() == "clarksville elementary school"
        and child.get("op") == "contains"
        for child in filter_children
    )
    joins = out["llm_plan"]["join_plan"].get("joins") or []
    assert any(str(item.get("table") or "").lower() == "dim_school" for item in joins)


def test_plan_injects_school_filter_for_quoted_school_phrase_prompt() -> None:
    class _ConceptRetrieval:
        def search(self, *, prompt, vertical_norm, max_concepts, deterministic_matches):
            del prompt, vertical_norm, max_concepts, deterministic_matches
            return {
                "query_text": 'Give me all the first and last names of all students at "Clarksville Elementary School"',
                "hits": [
                    {"concept_key": "FIRST_NAME", "score": 0.8, "source": "vector"},
                    {"concept_key": "LAST_NAME", "score": 0.79, "source": "vector"},
                    {"concept_key": "SCHOOL_NAME", "score": 0.74, "source": "vector"},
                ],
            }

    class _ConceptToColumn:
        def map_concepts_to_columns(self, **kwargs):
            del kwargs
            return {
                "concepts": ["FIRST_NAME", "LAST_NAME", "SCHOOL_NAME"],
                "mapped_columns": [
                    {"model_column_id": 5101, "workspace_table_id": 91, "table_name": "dim_student", "column_name": "first_name", "concept_key": "FIRST_NAME", "base_weight": 1.0, "effective_weight": 1.2, "final_score": 3.1},
                    {"model_column_id": 5102, "workspace_table_id": 91, "table_name": "dim_student", "column_name": "last_name", "concept_key": "LAST_NAME", "base_weight": 1.0, "effective_weight": 1.2, "final_score": 3.0},
                    {"model_column_id": 5103, "workspace_table_id": 92, "table_name": "dim_school", "column_name": "school_name", "concept_key": "SCHOOL_NAME", "base_weight": 1.0, "effective_weight": 1.2, "final_score": 2.9},
                ],
                "candidate_model_column_ids": [5101, 5102, 5103],
                "ranked_candidates_by_concept": {},
                "warnings": [],
            }

    class _ColumnVector:
        def search(self, **kwargs):
            del kwargs
            return {"filtered_to_candidate_count": 0, "hits": []}

    class _LLM:
        def chat_json(self, **kwargs):
            del kwargs
            return {
                "sql_json": {},
                "selected_columns": [],
                "filters": [],
                "join_plan": {},
                "confidence": 0.5,
                "notes": [],
            }

    class _ValueAliasResolver:
        def resolve(self, *, prompt, vertical_norm):
            del prompt, vertical_norm
            return []

    class _DomainSelector:
        def choose_domain_id(self, **kwargs):
            del kwargs
            return {"domain_id": None, "source": "auto", "threshold_met": False, "domains": []}

    svc = PlanService(
        sql=FakeForgeQueryPort(),
        deterministic=DeterministicMatcher(),
        concept_retrieval=_ConceptRetrieval(),
        concept_to_column=_ConceptToColumn(),
        column_vector=_ColumnVector(),
        llm_client=_LLM(),
        value_alias_resolver=_ValueAliasResolver(),
        domain_selector=_DomainSelector(),
    )

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "prompt": 'Give me all the first and last names of all students at "Clarksville Elementary School"',
        },
        include_llm=True,
    )

    filter_children = (out["llm_plan"]["sql_json"].get("filters") or {}).get("children") or []
    assert any(
        child["field"]["columnName"] == "school_name"
        and str(child.get("value") or "").lower() == "clarksville elementary school"
        for child in filter_children
    )


def test_filter_column_rank_prefers_dim_school_school_name() -> None:
    dim_school_rank = SqlJsonBuilder.filter_column_rank(
        concept_key="SCHOOL_NAME",
        row={
            "__selected__": False,
            "table_name": "dim_school",
            "column_name": "school_name",
            "effective_weight": 1.0,
            "model_column_id": 1,
        },
    )
    fact_rank = SqlJsonBuilder.filter_column_rank(
        concept_key="SCHOOL_NAME",
        row={
            "__selected__": False,
            "table_name": "fct_student_school_association",
            "column_name": "school_name",
            "effective_weight": 1.1,
            "model_column_id": 2,
        },
    )

    assert dim_school_rank < fact_rank


def test_build_default_projection_uses_semantic_projection_policy() -> None:
    validator = PlanValidator()

    out = validator._build_default_projection(
        intent_entity="student",
        mapped_columns=[
            {"model_column_id": 1, "table_name": "dim_student", "concept_key": "FIRST_NAME", "effective_weight": 1.0, "final_score": 2.0},
            {"model_column_id": 2, "table_name": "dim_student", "concept_key": "LAST_NAME", "effective_weight": 1.0, "final_score": 2.0},
            {"model_column_id": 3, "table_name": "dim_student", "concept_key": "ID", "effective_weight": 1.0, "final_score": 2.0},
        ],
    )

    assert out == [
        {"concept_key": "ID", "model_column_id": 3},
        {"concept_key": "FIRST_NAME", "model_column_id": 1},
        {"concept_key": "LAST_NAME", "model_column_id": 2},
    ]


def test_select_preferred_time_column_uses_semantic_time_policy() -> None:
    time_policy_svc = PlannerSemanticTimePolicyService()

    out = time_policy_svc.select_preferred_time_column(
        domain_hint="enrollment",
        mapped_columns_for_time_concept=[
            {"model_column_id": 2, "column_name": "year", "concept_key": "SCHOOL_YEAR", "final_score": 3.8},
            {"model_column_id": 1, "column_name": "school_year", "concept_key": "SCHOOL_YEAR", "final_score": 3.7},
        ],
    )

    assert out is not None
    assert out["model_column_id"] == 1


def test_plan_uses_tier2_school_slot_to_force_filter(monkeypatch) -> None:
    import app.services.semantic.plan.service as plan_service_module

    monkeypatch.setattr(plan_service_module, "NLP_TIER2_ENABLED", True)

    class _Deterministic:
        def match(self, prompt):
            del prompt
            return {"matched": [], "unmatched_tokens": []}

    class _ConceptRetrieval:
        def search(self, *, prompt, vertical_norm, max_concepts, deterministic_matches):
            del prompt, vertical_norm, max_concepts, deterministic_matches
            return {
                "query_text": "students at Clarksville Elementary School",
                "hits": [
                    {"concept_key": "STUDENT_ID", "score": 0.7, "source": "alias"},
                    {"concept_key": "SCHOOL_NAME", "score": 0.65, "source": "alias"},
                ],
            }

    class _ConceptToColumn:
        def map_concepts_to_columns(self, **kwargs):
            del kwargs
            return {
                "concepts": ["STUDENT_ID", "SCHOOL_NAME"],
                "mapped_columns": [
                    {
                        "model_column_id": 1,
                        "workspace_table_id": 10,
                        "table_name": "dim_student",
                        "column_name": "k_student",
                        "concept_key": "STUDENT_ID",
                        "weight": 1.0,
                        "final_score": 2.0,
                    },
                    {
                        "model_column_id": 2,
                        "workspace_table_id": 11,
                        "table_name": "dim_school",
                        "column_name": "school_name",
                        "concept_key": "SCHOOL_NAME",
                        "weight": 1.0,
                        "final_score": 2.5,
                    },
                ],
                "candidate_model_column_ids": [1, 2],
                "ranked_candidates_by_concept": {},
            }

    class _ColumnVector:
        def search(self, **kwargs):
            del kwargs
            return {
                "filtered_to_candidate_count": 2,
                "hits": [
                    {
                        "model_column_id": 2,
                        "workspace_table_id": 11,
                        "table_name": "dim_school",
                        "column_name": "school_name",
                        "concept_key": "SCHOOL_NAME",
                        "score": 0.9,
                    },
                    {
                        "model_column_id": 1,
                        "workspace_table_id": 10,
                        "table_name": "dim_student",
                        "column_name": "k_student",
                        "concept_key": "STUDENT_ID",
                        "score": 0.8,
                    },
                ],
            }

    class _LLM:
        def chat_json(self, **kwargs):
            del kwargs
            return {
                "sql_json": {"from": "dim_student"},
                "selected_columns": [{"concept_key": "STUDENT_ID", "model_column_id": 1}],
                "filters": [],
                "join_plan": {},
                "confidence": 0.8,
                "notes": [],
            }

    class _DomainSelector:
        def choose_domain_id(self, **kwargs):
            del kwargs
            return {"domain_id": None, "source": "auto", "threshold_met": False, "domains": []}

    class _ValueAliasResolver:
        def resolve(self, *, prompt, vertical_norm):
            del prompt, vertical_norm
            return []

    svc = PlanService(
        sql=FakeForgeQueryPort(),
        deterministic=_Deterministic(),
        concept_retrieval=_ConceptRetrieval(),
        concept_to_column=_ConceptToColumn(),
        column_vector=_ColumnVector(),
        llm_client=_LLM(),
        domain_selector=_DomainSelector(),
        value_alias_resolver=_ValueAliasResolver(),
        tier2_runner=lambda prompt: {
            "plan_ir": {
                "prompt": prompt,
                "entities": {"subject_entity": "student", "confidence": 0.9},
                "slots": {"school": [{"value": "Clarksville Elementary School", "confidence": 0.95}]},
                "topic": ["enrollment"],
                "operators": {"negation": False, "comparators": []},
                "intent": {"label": "intent_filter", "scores": {"intent_filter": 0.9}},
                "warnings": [],
            },
            "model": {"enabled": True, "version": "model-v1"},
            "timings_ms": {"tier2": 8},
        },
    )

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "prompt": "students at Clarksville Elementary School",
            "debug": True,
        },
        include_llm=True,
    )

    assert out["debug"]["timings_ms"]["tier2"] == 8
    assert out["debug"]["tier2"]["plan_ir"]["entities"]["subject_entity"] == "student"
    assert any(
        f.get("concept_key") == "SCHOOL_NAME" and "clarksville" in str(f.get("value") or "").lower()
        for f in out["llm_plan"]["filters"]
    )
