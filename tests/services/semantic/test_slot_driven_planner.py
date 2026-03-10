from __future__ import annotations

from app.services.semantic.plan_service import PlanService
from tests._support.fakes import FakeForgeQueryPort


def test_slot_driven_planner_enrollment_by_grade_current_school_year() -> None:
    class _SemanticExtractor:
        def extract(self, prompt):
            return {
                "normalized_text": prompt,
                "slots": {
                    "metric": ["student enrollment"],
                    "dimensions": ["by grade level"],
                    "subgroups": [],
                    "time_ranges": ["for the current school year"],
                    "org_schools": [],
                    "org_districts": [],
                },
                "by_label": {
                    "METRIC": ["student enrollment"],
                    "DIMENSION": ["by grade level"],
                    "TIME_RANGE": ["for the current school year"],
                },
                "ents": [],
                "model": {},
                "warnings": [],
            }

    class _Deterministic:
        def match(self, prompt):
            del prompt
            return {"matched": [], "unmatched_tokens": []}

    class _ConceptRetrieval:
        def search(self, **kwargs):
            prompt = str(kwargs.get("prompt") or "").lower()
            if "student enrollment" in prompt:
                return {
                    "query_text": prompt,
                    "hits": [
                        {"concept_key": "ENROLLMENT_COUNT", "score": 0.92, "source": "vector"},
                        {"concept_key": "STUDENT_ID", "score": 0.8, "source": "vector"},
                        {"concept_key": "GPA_APPLICABILITY", "score": 0.75, "source": "vector"},
                    ],
                }
            if "grade level" in prompt:
                return {
                    "query_text": prompt,
                    "hits": [
                        {"concept_key": "STUDENT_GRADE_LEVEL", "score": 0.91, "source": "vector"},
                        {"concept_key": "V_GRADE_LEVELS", "score": 0.82, "source": "vector"},
                    ],
                }
            return {"query_text": prompt, "hits": []}

    class _ConceptToColumn:
        def map_concepts_to_columns(self, **kwargs):
            del kwargs
            return {
                "concepts": ["ENROLLMENT_COUNT", "STUDENT_GRADE_LEVEL", "SCHOOL_YEAR", "GPA_APPLICABILITY", "GRADING_PERIOD"],
                "mapped_columns": [
                    {"model_column_id": 1001, "workspace_table_id": 1, "table_name": "dim_student", "column_name": "k_student", "concept_key": "ENROLLMENT_COUNT", "final_score": 4.0},
                    {"model_column_id": 1002, "workspace_table_id": 1, "table_name": "dim_student", "column_name": "grade_level", "concept_key": "STUDENT_GRADE_LEVEL", "final_score": 3.8},
                    {"model_column_id": 1003, "workspace_table_id": 2, "table_name": "fct_student_school_association", "column_name": "school_year", "concept_key": "SCHOOL_YEAR", "final_score": 3.7},
                    {"model_column_id": 1004, "workspace_table_id": 2, "table_name": "fct_student_school_association", "column_name": "grading_period", "concept_key": "GRADING_PERIOD", "final_score": 3.1},
                    {"model_column_id": 1005, "workspace_table_id": 2, "table_name": "fct_student_school_association", "column_name": "gpa_applicability", "concept_key": "GPA_APPLICABILITY", "final_score": 3.0},
                ],
                "warnings": [],
            }

    class _ColumnVector:
        def search(self, **kwargs):
            return {
                "filtered_to_candidate_count": len(list(kwargs.get("candidate_columns") or [])),
                "hits": list(kwargs.get("candidate_columns") or []),
            }

    class _DomainSelector:
        def choose_domain_id(self, **kwargs):
            del kwargs
            return {"domain_id": 11}

    class _LLM:
        def chat_json(self, **kwargs):
            del kwargs
            return {
                "sql_json": {},
                "selected_columns": [{"concept_key": "ENROLLMENT_COUNT", "model_column_id": 1001}],
                "filters": [],
                "join_plan": {},
                "confidence": 0.7,
                "notes": [],
            }

    svc = PlanService(
        sql=FakeForgeQueryPort(),
        deterministic=_Deterministic(),
        concept_retrieval=_ConceptRetrieval(),
        concept_to_column=_ConceptToColumn(),
        column_vector=_ColumnVector(),
        domain_selector=_DomainSelector(),
        llm_client=_LLM(),
        semantic_extractor=_SemanticExtractor(),
    )
    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "prompt": "Show student enrollment by grade level for the current school year.",
        },
        include_llm=True,
    )

    sql_json = out["llm_plan"]["sql_json"]
    assert isinstance((sql_json.get("aggs") or {}).get("metrics"), list)
    assert (sql_json.get("aggs") or {}).get("metrics")
    group_by = (sql_json.get("aggs") or {}).get("groupBy") or []
    assert any(str(item.get("columnName") or "").lower() == "grade_level" for item in group_by)
    filters = (sql_json.get("filters") or {}).get("children") or []
    assert any(str(item.get("field", {}).get("columnName") or "").lower() == "school_year" for item in filters)
    assert any(str(item.get("value") or "") == "CURRENT_SCHOOL_YEAR" for item in filters)
    selected_columns = sql_json.get("columns") or []
    assert len(selected_columns) >= 2
    forbidden = {"grading_period", "gpa_applicability"}
    assert not any(str(item.get("field", {}).get("columnName") or "").lower() in forbidden for item in selected_columns)


def test_slot_driven_planner_list_student_ids_keeps_identifiers_without_agg() -> None:
    class _SemanticExtractor:
        def extract(self, prompt):
            return {
                "normalized_text": prompt,
                "slots": {
                    "metric": [],
                    "dimensions": ["grade 9"],
                    "subgroups": [],
                    "time_ranges": ["this school year"],
                    "org_schools": [],
                    "org_districts": [],
                },
                "by_label": {"DIMENSION": ["grade 9"], "TIME_RANGE": ["this school year"]},
                "ents": [],
                "model": {},
                "warnings": [],
            }

    class _Deterministic:
        def match(self, prompt):
            del prompt
            return {"matched": [], "unmatched_tokens": []}

    class _ConceptRetrieval:
        def search(self, **kwargs):
            prompt = str(kwargs.get("prompt") or "").lower()
            if "grade 9" in prompt:
                return {
                    "query_text": prompt,
                    "hits": [
                        {"concept_key": "STUDENT_ID", "score": 0.89, "source": "vector"},
                        {"concept_key": "STUDENT_GRADE_LEVEL", "score": 0.86, "source": "vector"},
                    ],
                }
            return {"query_text": prompt, "hits": []}

    class _ConceptToColumn:
        def map_concepts_to_columns(self, **kwargs):
            del kwargs
            return {
                "concepts": ["STUDENT_ID", "STUDENT_GRADE_LEVEL", "SCHOOL_YEAR"],
                "mapped_columns": [
                    {"model_column_id": 2001, "workspace_table_id": 10, "table_name": "dim_student", "column_name": "k_student", "concept_key": "STUDENT_ID", "final_score": 4.0},
                    {"model_column_id": 2002, "workspace_table_id": 10, "table_name": "dim_student", "column_name": "grade_level", "concept_key": "STUDENT_GRADE_LEVEL", "final_score": 3.8},
                    {"model_column_id": 2003, "workspace_table_id": 11, "table_name": "fct_student_school_association", "column_name": "school_year", "concept_key": "SCHOOL_YEAR", "final_score": 3.7},
                ],
                "warnings": [],
            }

    class _ColumnVector:
        def search(self, **kwargs):
            return {
                "filtered_to_candidate_count": len(list(kwargs.get("candidate_columns") or [])),
                "hits": list(kwargs.get("candidate_columns") or []),
            }

    class _DomainSelector:
        def choose_domain_id(self, **kwargs):
            del kwargs
            return {"domain_id": 11}

    class _LLM:
        def chat_json(self, **kwargs):
            del kwargs
            return {
                "sql_json": {},
                "selected_columns": [{"concept_key": "STUDENT_ID", "model_column_id": 2001}],
                "filters": [{"concept_key": "STUDENT_GRADE_LEVEL", "op": "=", "value": "9"}],
                "join_plan": {},
                "confidence": 0.8,
                "notes": [],
            }

    svc = PlanService(
        sql=FakeForgeQueryPort(),
        deterministic=_Deterministic(),
        concept_retrieval=_ConceptRetrieval(),
        concept_to_column=_ConceptToColumn(),
        column_vector=_ColumnVector(),
        domain_selector=_DomainSelector(),
        llm_client=_LLM(),
        semantic_extractor=_SemanticExtractor(),
    )
    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "prompt": "List student ids for grade 9 this school year",
        },
        include_llm=True,
    )

    selected = out["llm_plan"]["selected_columns"]
    assert any(str(item.get("concept_key") or "").upper() == "STUDENT_ID" for item in selected)
    sql_json = out["llm_plan"]["sql_json"]
    assert not isinstance(sql_json.get("aggs"), dict) or not (sql_json.get("aggs") or {}).get("metrics")
    filters = (sql_json.get("filters") or {}).get("children") or []
    assert any(str(item.get("field", {}).get("columnName") or "").lower() == "school_year" for item in filters)
    assert any(str(item.get("value") or "") == "CURRENT_SCHOOL_YEAR" for item in filters)


def test_slot_driven_planner_listing_prompt_does_not_force_count() -> None:
    class _SemanticExtractor:
        def extract(self, prompt):
            return {
                "normalized_text": prompt,
                "slots": {
                    "metric": ["student enrollment"],
                    "dimensions": [],
                    "subgroups": [],
                    "time_ranges": [],
                    "org_schools": [],
                    "org_districts": [],
                },
                "by_label": {"METRIC": ["student enrollment"]},
                "ents": [],
                "model": {},
                "warnings": [],
            }

    class _Deterministic:
        def match(self, prompt):
            del prompt
            return {"matched": [], "unmatched_tokens": []}

    class _ConceptRetrieval:
        def search(self, **kwargs):
            del kwargs
            return {
                "query_text": "student enrollment",
                "hits": [{"concept_key": "ENROLLMENT_COUNT", "score": 0.92, "source": "vector"}],
            }

    class _ConceptToColumn:
        def map_concepts_to_columns(self, **kwargs):
            del kwargs
            return {
                "concepts": ["ENROLLMENT_COUNT", "RACE_ETHNICITY", "COUNTY_NAME"],
                "mapped_columns": [
                    {"model_column_id": 3001, "workspace_table_id": 24, "table_name": "dim_student", "column_name": "race_ethnicity", "concept_key": "RACE_ETHNICITY", "final_score": 3.9},
                    {"model_column_id": 3002, "workspace_table_id": 20, "table_name": "dim_school", "column_name": "name_of_county", "concept_key": "COUNTY_NAME", "final_score": 3.8},
                    {"model_column_id": 3003, "workspace_table_id": 24, "table_name": "dim_student", "column_name": "k_student", "concept_key": "ENROLLMENT_COUNT", "final_score": 3.7},
                ],
                "warnings": [],
            }

    class _ColumnVector:
        def search(self, **kwargs):
            return {
                "filtered_to_candidate_count": len(list(kwargs.get("candidate_columns") or [])),
                "hits": list(kwargs.get("candidate_columns") or []),
            }

    class _DomainSelector:
        def choose_domain_id(self, **kwargs):
            del kwargs
            return {"domain_id": 6}

    class _LLM:
        def chat_json(self, **kwargs):
            del kwargs
            return {
                "sql_json": {"domainId": 6},
                "selected_columns": [
                    {"concept_key": "RACE_ETHNICITY", "model_column_id": 3001},
                    {"concept_key": "COUNTY_NAME", "model_column_id": 3002},
                ],
                "filters": [{"concept_key": "COUNTY_NAME", "op": "=", "value": "MONTGOMERY"}],
                "join_plan": {},
                "confidence": 0.8,
                "notes": [],
            }

    svc = PlanService(
        sql=FakeForgeQueryPort(),
        deterministic=_Deterministic(),
        concept_retrieval=_ConceptRetrieval(),
        concept_to_column=_ConceptToColumn(),
        column_vector=_ColumnVector(),
        domain_selector=_DomainSelector(),
        llm_client=_LLM(),
        semantic_extractor=_SemanticExtractor(),
    )
    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "prompt": "Show me all the african american students enrolled in montgomery county schools",
        },
        include_llm=True,
    )

    sql_json = out["llm_plan"]["sql_json"]
    metrics = ((sql_json.get("aggs") or {}).get("metrics") or []) if isinstance(sql_json.get("aggs"), dict) else []
    assert metrics == []


def test_slot_driven_planner_grounds_org_district_and_race_filters() -> None:
    prompt = "Show me all the african american students enrolled in montgomery county district schools"

    class _SemanticExtractor:
        def extract(self, raw_prompt):
            return {
                "normalized_text": raw_prompt,
                "slots": {
                    "metric": ["enrolled"],
                    "dimensions": ["district"],
                    "subgroups": ["african american students"],
                    "time_ranges": [],
                    "org_schools": [],
                    "org_districts": ["montgomery county"],
                },
                "by_label": {
                    "METRIC": ["enrolled"],
                    "DIMENSION": ["district"],
                    "SUBGROUP": ["african american students"],
                    "ORG_DISTRICT": ["montgomery county"],
                },
                "ents": [
                    {"start": 16, "end": 41, "label": "SUBGROUP", "text": "african american students"},
                    {"start": 54, "end": 71, "label": "ORG_DISTRICT", "text": "montgomery county"},
                ],
                "model": {},
                "warnings": [],
            }

    class _Deterministic:
        def match(self, raw_prompt):
            del raw_prompt
            return {"matched": [], "unmatched_tokens": []}

    class _ConceptRetrieval:
        def search(self, **kwargs):
            query = str(kwargs.get("prompt") or "").lower()
            if "district" in query:
                return {
                    "query_text": query,
                    "hits": [
                        {"concept_key": "DISTRICT_NAME", "score": 0.92, "source": "vector"},
                        {"concept_key": "COUNTY_NAME", "score": 0.9, "source": "vector"},
                    ],
                }
            if "african american" in query:
                return {
                    "query_text": query,
                    "hits": [
                        {"concept_key": "STUDENT_ID", "score": 0.79, "source": "vector"},
                    ],
                }
            return {"query_text": query, "hits": []}

    class _ConceptToColumn:
        def map_concepts_to_columns(self, **kwargs):
            del kwargs
            return {
                "concepts": ["DISTRICT_NAME", "RACE", "STUDENT_ID", "COUNTY_NAME"],
                "mapped_columns": [
                    {"model_column_id": 266, "workspace_table_id": 20, "table_name": "dim_school", "column_name": "lea_name", "concept_key": "DISTRICT_NAME", "final_score": 4.2},
                    {"model_column_id": 281, "workspace_table_id": 20, "table_name": "dim_school", "column_name": "name_of_county", "concept_key": "COUNTY_NAME", "final_score": 4.1},
                    {"model_column_id": 365, "workspace_table_id": 24, "table_name": "dim_student", "column_name": "race_ethnicity", "concept_key": "RACE", "final_score": 4.0},
                    {"model_column_id": 1064, "workspace_table_id": 32, "table_name": "fct_student_school_association", "column_name": "k_student", "concept_key": "STUDENT_ID", "final_score": 3.6},
                ],
                "warnings": [],
            }

    class _ColumnVector:
        def search(self, **kwargs):
            candidate_columns = list(kwargs.get("candidate_columns") or [])
            return {
                "filtered_to_candidate_count": len(candidate_columns),
                "hits": candidate_columns,
            }

    class _DomainSelector:
        def choose_domain_id(self, **kwargs):
            del kwargs
            return {"domain_id": 6}

    class _LLM:
        def chat_json(self, **kwargs):
            del kwargs
            return {
                "sql_json": {},
                "selected_columns": [{"concept_key": "DISTRICT_NAME", "model_column_id": 266}],
                "filters": [
                    {
                        "concept_key": "DISTRICT_NAME",
                        "op": "=",
                        "value": prompt,
                    }
                ],
                "join_plan": {},
                "confidence": 0.78,
                "notes": [],
            }

    svc = PlanService(
        sql=FakeForgeQueryPort(),
        deterministic=_Deterministic(),
        concept_retrieval=_ConceptRetrieval(),
        concept_to_column=_ConceptToColumn(),
        column_vector=_ColumnVector(),
        domain_selector=_DomainSelector(),
        llm_client=_LLM(),
        semantic_extractor=_SemanticExtractor(),
    )

    out = svc.plan(
        {
            "workspace_id": "ws-1",
            "vertical_norm": "education",
            "prompt": prompt,
        },
        include_llm=True,
    )

    llm_plan = out["llm_plan"]
    sql_json = llm_plan["sql_json"]
    filter_children = (sql_json.get("filters") or {}).get("children") or []
    assert any(
        str(item.get("field", {}).get("columnName") or "").lower() == "lea_name"
        and str(item.get("value") or "").strip().lower() == "montgomery county"
        for item in filter_children
    )
    assert any(
        str(item.get("field", {}).get("columnName") or "").lower() == "race_ethnicity"
        and str(item.get("value") or "").strip() == "Black - African American"
        for item in filter_children
    )
    assert not ((sql_json.get("aggs") or {}).get("metrics") if isinstance(sql_json.get("aggs"), dict) else [])
    assert not any(
        str(item.get("value") or "").strip().lower() == prompt.lower()
        for item in filter_children
    )

    mapped_columns = (out.get("concept_mapping") or {}).get("mapped_columns") or []
    assert any(str(row.get("column_name") or "").lower() == "race_ethnicity" for row in mapped_columns)
    assert any(str(row.get("table_name") or "").lower() == "fct_student_school_association" for row in mapped_columns)
