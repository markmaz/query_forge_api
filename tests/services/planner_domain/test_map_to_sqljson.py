from __future__ import annotations

from app.services.planner_domain.map_to_sqljson import map_plan_v2_to_sqljson


def _capabilities() -> dict:
    return {
        "domain_id": 6,
        "domain_version": 2,
        "dimensions": [
            {
                "column_key": "wt20.county_fips_code",
                "label": "County",
                "data_type": "int",
                "filterable": True,
                "workspace_table_id": 20,
                "model_column_id": 286,
                "column_name": "county_fips_code",
            }
        ],
        "domain_metrics": [{"metric_key": "enrollment_count", "label": "Enrollment Count", "kind": "count", "agg": "count"}],
        "user_metrics": [],
        "overlay_metrics": [{"overlay_key": "students_per_teacher", "label": "Students per Teacher", "requires": [6, 5]}],
        "time_columns": [],
    }


def test_map_to_sqljson_resolves_domain_metric() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "trace-1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 6,
        "intent": "aggregate",
        "selects": {
            "dimensions": [{"column_key": "wt20.county_fips_code", "label": "County"}],
            "metrics": [{"metric_ref": "domain_metric:enrollment_count", "label": "Enrollment"}],
        },
        "filters": [],
        "time": {},
        "grouping": {"group_by": ["wt20.county_fips_code"], "order_by": []},
    }
    out = map_plan_v2_to_sqljson(plan_json=plan, capabilities=_capabilities(), prompt="students by county")
    metrics = ((out.get("aggs") or {}).get("metrics") or [])
    assert metrics
    assert metrics[0]["fn"] == "count"
    assert metrics[0]["metric_ref"] == "domain_metric:enrollment_count"
    assert (metrics[0].get("field") or {}).get("columnName") == "county_fips_code"
    sorting = out.get("sorting") or []
    assert sorting
    assert sorting[0]["dir"] == "asc"
    assert (sorting[0].get("col") or {}).get("columnName") == "county_fips_code"


def test_map_to_sqljson_emits_overlay_metric_node() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "trace-2",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 6,
        "intent": "aggregate",
        "selects": {
            "dimensions": [{"column_key": "wt20.county_fips_code", "label": "County"}],
            "metrics": [{"metric_ref": "overlay:students_per_teacher", "label": "Students per Teacher"}],
        },
        "filters": [],
        "time": {},
        "grouping": {"group_by": ["wt20.county_fips_code"], "order_by": []},
    }
    out = map_plan_v2_to_sqljson(
        plan_json=plan,
        capabilities=_capabilities(),
        prompt="students per teacher by county",
    )
    metrics = ((out.get("aggs") or {}).get("metrics") or [])
    assert metrics
    overlay = metrics[0]
    assert overlay["fn"] == "overlay_metric"
    assert overlay["overlay_key"] == "students_per_teacher"
    assert overlay["metric_ref"] == "overlay:students_per_teacher"


def test_map_to_sqljson_list_intent_without_metrics_disables_aggs_and_keeps_columns() -> None:
    capabilities = {
        "domain_id": 6,
        "domain_version": 2,
        "dimensions": [
            {
                "column_key": "wt24.k_student",
                "label": "Student Key",
                "data_type": "string",
                "filterable": True,
                "workspace_table_id": 24,
                "model_column_id": 348,
                "column_name": "k_student",
            },
            {
                "column_key": "wt24.first_name",
                "label": "First Name",
                "data_type": "string",
                "filterable": True,
                "workspace_table_id": 24,
                "model_column_id": 354,
                "column_name": "first_name",
            },
            {
                "column_key": "wt24.last_name",
                "label": "Last Name",
                "data_type": "string",
                "filterable": True,
                "workspace_table_id": 24,
                "model_column_id": 356,
                "column_name": "last_name",
            },
            {
                "column_key": "wt20.school_name",
                "label": "School Name",
                "data_type": "string",
                "filterable": True,
                "workspace_table_id": 20,
                "model_column_id": 99,
                "column_name": "school_name",
            },
        ],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
        "time_columns": [],
    }
    plan = {
        "schema_version": 2,
        "trace_id": "trace-3",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 6,
        "intent": "list",
        "selects": {
            "dimensions": [
                {"column_key": "wt24.k_student", "label": "Student Key"},
                {"column_key": "wt24.first_name", "label": "First Name"},
                {"column_key": "wt24.last_name", "label": "Last Name"},
                {"column_key": "wt20.school_name", "label": "School Name"},
            ],
            "metrics": [],
        },
        "filters": [],
        "time": {},
        "grouping": {
            "group_by": ["wt24.k_student", "wt24.first_name", "wt24.last_name"],
            "order_by": [],
        },
    }

    out = map_plan_v2_to_sqljson(
        plan_json=plan,
        capabilities=capabilities,
        prompt="Show me all the students with a first name like Holden and a last name like Black",
    )
    aggs = out.get("aggs") or {}
    assert aggs.get("enabled") is False
    assert (aggs.get("metrics") or []) == []
    assert (aggs.get("groupBy") or []) == []
    columns = out.get("columns") or []
    assert any((c.get("columnName") or (c.get("field") or {}).get("columnName")) == "school_name" for c in columns)


def test_map_to_sqljson_maps_not_in_and_null_operators() -> None:
    capabilities = {
        "domain_id": 6,
        "domain_version": 1,
        "dimensions": [
            {
                "column_key": "wt24.state_code",
                "label": "State",
                "data_type": "string",
                "filterable": True,
                "workspace_table_id": 24,
                "model_column_id": 501,
                "column_name": "state_code",
            },
            {
                "column_key": "wt24.middle_name",
                "label": "Middle Name",
                "data_type": "string",
                "filterable": True,
                "workspace_table_id": 24,
                "model_column_id": 502,
                "column_name": "middle_name",
            },
        ],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
        "time_columns": [],
    }
    plan = {
        "schema_version": 2,
        "trace_id": "trace-4",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 6,
        "intent": "list",
        "selects": {"dimensions": [{"column_key": "wt24.state_code"}], "metrics": []},
        "filters": [
            {"column_key": "wt24.state_code", "op": "not_in", "values": ["CA", "NY"]},
            {"column_key": "wt24.middle_name", "op": "is_null"},
        ],
        "time": {},
        "grouping": {"group_by": ["wt24.state_code"], "order_by": []},
    }

    out = map_plan_v2_to_sqljson(
        plan_json=plan,
        capabilities=capabilities,
        prompt="list students not in CA or NY with no middle name",
    )
    children = ((out.get("filters") or {}).get("children") or [])
    assert len(children) == 2
    assert children[0]["op"] == "not_in"
    assert children[0]["value"] == ["CA", "NY"]
    assert children[1]["op"] == "is_null"


def test_map_to_sqljson_prefers_identifier_fallback_for_enrollment_metric() -> None:
    capabilities = {
        "domain_id": 7,
        "domain_version": 1,
        "dimensions": [
            {
                "column_key": "wt24.grade_level",
                "label": "Grade",
                "data_type": "string",
                "filterable": True,
                "workspace_table_id": 24,
                "model_column_id": 363,
                "column_name": "grade_level",
            },
            {
                "column_key": "wt24.k_student_xyear",
                "label": "Student Year Key",
                "data_type": "string",
                "filterable": True,
                "workspace_table_id": 24,
                "model_column_id": 349,
                "column_name": "k_student_xyear",
            },
            {
                "column_key": "wt24.student_unique_id",
                "label": "Student Unique Id",
                "data_type": "string",
                "filterable": True,
                "workspace_table_id": 24,
                "model_column_id": 350,
                "column_name": "student_unique_id",
            },
        ],
        "domain_metrics": [{"metric_key": "enrollment_count", "label": "Enrollment Count", "kind": "count", "agg": "count"}],
        "user_metrics": [],
        "overlay_metrics": [],
        "time_columns": [],
    }
    plan = {
        "schema_version": 2,
        "trace_id": "trace-5",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 7,
        "intent": "aggregate",
        "selects": {
            "dimensions": [{"column_key": "wt24.grade_level", "label": "Grade"}],
            "metrics": [{"metric_ref": "domain_metric:enrollment_count", "label": "Enrollment Count"}],
        },
        "filters": [],
        "time": {},
        "grouping": {"group_by": ["wt24.grade_level"], "order_by": []},
    }
    out = map_plan_v2_to_sqljson(plan_json=plan, capabilities=capabilities, prompt="enrollment by grade")
    metrics = ((out.get("aggs") or {}).get("metrics") or [])
    assert metrics
    assert metrics[0]["fn"] == "count"
    assert (metrics[0].get("field") or {}).get("columnName") == "student_unique_id"


def test_map_to_sqljson_default_sort_uses_first_selected_column() -> None:
    capabilities = {
        "domain_id": 4,
        "domain_version": 1,
        "dimensions": [
            {
                "column_key": "wt20.school_name",
                "label": "School Name",
                "data_type": "string",
                "filterable": True,
                "workspace_table_id": 20,
                "model_column_id": 99,
                "column_name": "school_name",
            },
            {
                "column_key": "wt20.lea_name",
                "label": "LEA Name",
                "data_type": "string",
                "filterable": True,
                "workspace_table_id": 20,
                "model_column_id": 266,
                "column_name": "lea_name",
            },
        ],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
        "time_columns": [],
    }
    plan = {
        "schema_version": 2,
        "trace_id": "trace-6",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 4,
        "intent": "list",
        "selects": {
            "dimensions": [{"column_key": "wt20.school_name"}, {"column_key": "wt20.lea_name"}],
            "metrics": [],
        },
        "filters": [],
        "time": {},
        "grouping": {"group_by": ["wt20.school_name", "wt20.lea_name"], "order_by": []},
    }
    out = map_plan_v2_to_sqljson(plan_json=plan, capabilities=capabilities, prompt="show schools")
    sorting = out.get("sorting") or []
    assert sorting
    assert sorting[0]["dir"] == "asc"
    assert (sorting[0].get("col") or {}).get("columnName") == "school_name"


def test_map_to_sqljson_honors_explicit_order_by_dimension_column_key() -> None:
    capabilities = {
        "domain_id": 5,
        "domain_version": 1,
        "dimensions": [
            {
                "column_key": "wt20.school_name",
                "label": "School Name",
                "data_type": "string",
                "filterable": True,
                "workspace_table_id": 20,
                "model_column_id": 99,
                "column_name": "school_name",
            },
            {
                "column_key": "wt30.position_title",
                "label": "Position Title",
                "data_type": "string",
                "filterable": True,
                "workspace_table_id": 30,
                "model_column_id": 602,
                "column_name": "position_title",
            },
        ],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
        "time_columns": [],
    }
    plan = {
        "schema_version": 2,
        "trace_id": "trace-7",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 5,
        "intent": "list",
        "selects": {
            "dimensions": [{"column_key": "wt20.school_name"}, {"column_key": "wt30.position_title"}],
            "metrics": [],
        },
        "filters": [],
        "time": {},
        "grouping": {
            "group_by": ["wt20.school_name", "wt30.position_title"],
            "order_by": [{"by": "wt30.position_title", "dir": "asc"}],
        },
    }
    out = map_plan_v2_to_sqljson(plan_json=plan, capabilities=capabilities, prompt="show staff sorted by position")
    sorting = out.get("sorting") or []
    assert sorting
    assert sorting[0]["dir"] == "asc"
    assert (sorting[0].get("col") or {}).get("columnName") == "position_title"


def test_map_to_sqljson_honors_explicit_order_by_dimension_prefixed_form() -> None:
    capabilities = {
        "domain_id": 5,
        "domain_version": 1,
        "dimensions": [
            {
                "column_key": "wt20.school_name",
                "label": "School Name",
                "data_type": "string",
                "filterable": True,
                "workspace_table_id": 20,
                "model_column_id": 99,
                "column_name": "school_name",
            },
            {
                "column_key": "wt30.position_title",
                "label": "Position Title",
                "data_type": "string",
                "filterable": True,
                "workspace_table_id": 30,
                "model_column_id": 602,
                "column_name": "position_title",
            },
        ],
        "domain_metrics": [],
        "user_metrics": [],
        "overlay_metrics": [],
        "time_columns": [],
    }
    plan = {
        "schema_version": 2,
        "trace_id": "trace-8",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 5,
        "intent": "list",
        "selects": {
            "dimensions": [{"column_key": "wt20.school_name"}, {"column_key": "wt30.position_title"}],
            "metrics": [],
        },
        "filters": [],
        "time": {},
        "grouping": {
            "group_by": ["wt20.school_name", "wt30.position_title"],
            "order_by": [{"by": "dimension:wt30.position_title", "dir": "desc"}],
        },
    }
    out = map_plan_v2_to_sqljson(plan_json=plan, capabilities=capabilities, prompt="show staff sorted by position desc")
    sorting = out.get("sorting") or []
    assert sorting
    assert sorting[0]["dir"] == "desc"
    assert (sorting[0].get("col") or {}).get("columnName") == "position_title"
