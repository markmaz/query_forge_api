from __future__ import annotations

from app.services.planner_domain.validate_v2 import validate_and_repair_plan_v2


def _capabilities(with_overlay: bool = True, with_birth_filter_only: bool = False) -> dict:
    overlays = [{"overlay_key": "students_per_teacher", "label": "Students per Teacher", "requires": [6, 5]}]
    filter_columns = []
    if with_birth_filter_only:
        filter_columns.append(
            {
                "column_key": "wt24.birth_country",
                "label": "Birth Country",
                "data_type": "string",
                "filterable": True,
                "workspace_table_id": 24,
                "model_column_id": 359,
                "column_name": "birth_country",
            }
        )
    return {
        "domain_id": 6,
        "domain_version": 3,
        "dimensions": [
            {
                "column_key": "wt20.county_fips_code",
                "label": "County Fips Code",
                "data_type": "int",
                "filterable": True,
                "workspace_table_id": 20,
                "model_column_id": 286,
                "column_name": "county_fips_code",
            },
            {
                "column_key": "wt61.school_year",
                "label": "School Year",
                "data_type": "string",
                "filterable": True,
                "workspace_table_id": 61,
                "model_column_id": 1091,
                "column_name": "school_year",
            },
        ],
        "domain_metrics": [{"metric_key": "enrollment_count", "label": "Enrollment Count", "kind": "count", "agg": "count"}],
        "user_metrics": [],
        "overlay_metrics": overlays if with_overlay else [],
        "filter_columns": filter_columns,
        "time_columns": [
            {
                "column_key": "wt61.school_year",
                "label": "School Year",
                "data_type": "string",
                "filterable": True,
                "workspace_table_id": 61,
                "model_column_id": 1091,
                "column_name": "school_year",
            }
        ],
    }


def test_validator_rejects_dimension_not_in_domain() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 6,
        "intent": "aggregate",
        "selects": {
            "dimensions": [{"column_key": "wt999.unknown"}],
            "metrics": [{"metric_ref": "domain_metric:enrollment_count"}],
        },
        "filters": [],
        "time": {},
        "grouping": {"group_by": [], "order_by": []},
    }

    result = validate_and_repair_plan_v2(
        plan_json=plan,
        capabilities=_capabilities(),
        prompt="students by county",
        expected_base_domain_id=6,
    )
    assert result.is_valid is False
    assert any(issue["code"] == "invalid_dimension_column" for issue in result.issues)


def test_validator_rejects_overlay_metric_when_not_available() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 6,
        "intent": "aggregate",
        "selects": {
            "dimensions": [{"column_key": "wt20.county_fips_code"}],
            "metrics": [{"metric_ref": "overlay:students_per_teacher"}],
        },
        "filters": [],
        "time": {},
        "grouping": {"group_by": ["wt20.county_fips_code"], "order_by": []},
    }

    result = validate_and_repair_plan_v2(
        plan_json=plan,
        capabilities=_capabilities(with_overlay=False),
        prompt="students per teacher by county",
        expected_base_domain_id=6,
    )
    assert result.is_valid is False
    assert any(issue["code"] == "unknown_metric_ref" for issue in result.issues)


def test_validator_normalizes_group_by_to_dimensions() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 6,
        "intent": "aggregate",
        "selects": {
            "dimensions": [{"column_key": "wt20.county_fips_code"}],
            "metrics": [{"metric_ref": "domain_metric:enrollment_count"}],
        },
        "filters": [],
        "time": {},
        "grouping": {"group_by": [], "order_by": []},
    }

    result = validate_and_repair_plan_v2(
        plan_json=plan,
        capabilities=_capabilities(),
        prompt="students by county",
        expected_base_domain_id=6,
    )
    assert result.is_valid is True
    assert result.plan_json["grouping"]["group_by"] == ["wt20.county_fips_code"]
    assert "normalized_group_by_dimensions" in result.repairs_applied


def test_validator_allows_filter_only_birth_country_column() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 6,
        "intent": "list",
        "selects": {
            "dimensions": [{"column_key": "wt20.county_fips_code"}],
            "metrics": [],
        },
        "filters": [
            {"column_key": "wt24.birth_country", "op": "equals", "value": "United States"},
        ],
        "time": {},
        "grouping": {"group_by": ["wt20.county_fips_code"], "order_by": []},
    }

    result = validate_and_repair_plan_v2(
        plan_json=plan,
        capabilities=_capabilities(with_birth_filter_only=True),
        prompt="list students not born in the us",
        expected_base_domain_id=6,
    )
    assert result.is_valid is True
    assert result.plan_json["filters"][0]["column_key"] == "wt24.birth_country"


def test_validator_drops_invalid_filter_column_with_repair() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 6,
        "intent": "list",
        "selects": {
            "dimensions": [{"column_key": "wt20.county_fips_code"}],
            "metrics": [],
        },
        "filters": [
            {"column_key": "wt999.unknown", "op": "equals", "value": "x"},
        ],
        "time": {},
        "grouping": {"group_by": ["wt20.county_fips_code"], "order_by": []},
    }

    result = validate_and_repair_plan_v2(
        plan_json=plan,
        capabilities=_capabilities(),
        prompt="students",
        expected_base_domain_id=6,
    )
    assert result.is_valid is True
    assert result.plan_json["filters"] == []
    assert "dropped_invalid_filter:wt999.unknown" in result.repairs_applied


def test_validator_drops_self_referential_filter_value() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 6,
        "intent": "list",
        "selects": {
            "dimensions": [{"column_key": "wt20.county_fips_code"}],
            "metrics": [],
        },
        "filters": [
            {"column_key": "wt20.county_fips_code", "op": "=", "value": "wt20.county_fips_code"},
        ],
        "time": {},
        "grouping": {"group_by": ["wt20.county_fips_code"], "order_by": []},
    }

    result = validate_and_repair_plan_v2(
        plan_json=plan,
        capabilities=_capabilities(),
        prompt="students by county",
        expected_base_domain_id=6,
    )
    assert result.is_valid is True
    assert result.plan_json["filters"] == []
    assert "removed_self_referential_filter" in result.repairs_applied


def test_validator_drops_column_token_literal_filter_value() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 6,
        "intent": "list",
        "selects": {
            "dimensions": [{"column_key": "wt20.county_fips_code"}],
            "metrics": [],
        },
        "filters": [
            {"column_key": "wt20.county_fips_code", "op": "=", "value": "wt999.unknown"},
        ],
        "time": {},
        "grouping": {"group_by": ["wt20.county_fips_code"], "order_by": []},
    }

    result = validate_and_repair_plan_v2(
        plan_json=plan,
        capabilities=_capabilities(),
        prompt="students by county",
        expected_base_domain_id=6,
    )
    assert result.is_valid is True
    assert result.plan_json["filters"] == []
    assert "removed_column_token_filter_value" in result.repairs_applied


def test_validator_drops_missing_filter_value_for_comparison_ops() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 6,
        "intent": "list",
        "selects": {
            "dimensions": [{"column_key": "wt20.county_fips_code"}],
            "metrics": [],
        },
        "filters": [
            {"column_key": "wt20.county_fips_code", "op": "lt", "value": None},
        ],
        "time": {},
        "grouping": {"group_by": ["wt20.county_fips_code"], "order_by": []},
    }

    result = validate_and_repair_plan_v2(
        plan_json=plan,
        capabilities=_capabilities(),
        prompt="students by county",
        expected_base_domain_id=6,
    )
    assert result.is_valid is True
    assert result.plan_json["filters"] == []
    assert "removed_missing_filter_value" in result.repairs_applied


def test_validator_keeps_valid_filter_when_same_column_invalid_in_selects() -> None:
    capabilities = _capabilities()
    capabilities["filter_columns"] = [
        {
            "column_key": "wt24.last_name",
            "label": "Last Name",
            "data_type": "string",
            "filterable": True,
            "workspace_table_id": 24,
            "model_column_id": 356,
            "column_name": "last_name",
        }
    ]
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 6,
        "intent": "list",
        "selects": {
            "dimensions": [
                {"column_key": "wt20.county_fips_code"},
                {"column_key": "wt24.last_name"},
            ],
            "metrics": [],
        },
        "filters": [
            {"column_key": "wt24.last_name", "op": "equals", "value": "Black"},
        ],
        "time": {},
        "grouping": {"group_by": ["wt20.county_fips_code", "wt24.last_name"], "order_by": []},
    }

    result = validate_and_repair_plan_v2(
        plan_json=plan,
        capabilities=capabilities,
        prompt="Find all students with a last name of Black",
        expected_base_domain_id=6,
    )
    assert result.is_valid is False
    assert any(issue["code"] == "invalid_dimension_column" for issue in result.issues)
    assert result.plan_json["filters"] == [{"column_key": "wt24.last_name", "op": "equals", "value": "Black"}]
    assert "dropped_invalid_filter:wt24.last_name" not in result.repairs_applied


def test_validator_drops_known_non_filterable_column_from_filters() -> None:
    capabilities = _capabilities()
    capabilities["dimensions"].append(
        {
            "column_key": "wt24.ssn",
            "label": "SSN",
            "data_type": "string",
            "filterable": False,
            "workspace_table_id": 24,
            "model_column_id": 9999,
            "column_name": "ssn",
        }
    )
    capabilities["filter_columns"] = []
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 6,
        "intent": "list",
        "selects": {"dimensions": [{"column_key": "wt20.county_fips_code"}], "metrics": []},
        "filters": [{"column_key": "wt24.ssn", "op": "equals", "value": "123"}],
        "time": {},
        "grouping": {"group_by": ["wt20.county_fips_code"], "order_by": []},
    }

    result = validate_and_repair_plan_v2(
        plan_json=plan,
        capabilities=capabilities,
        prompt="students",
        expected_base_domain_id=6,
    )
    assert result.is_valid is True
    assert result.plan_json["filters"] == []
    assert "dropped_invalid_filter:wt24.ssn" in result.repairs_applied


def test_validator_preserves_domain_name_field() -> None:
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 6,
        "domain_name": "Enrollment",
        "intent": "list",
        "selects": {"dimensions": [{"column_key": "wt20.county_fips_code"}], "metrics": []},
        "filters": [],
        "time": {},
        "grouping": {"group_by": ["wt20.county_fips_code"], "order_by": []},
    }
    result = validate_and_repair_plan_v2(
        plan_json=plan,
        capabilities=_capabilities(),
        prompt="students by county",
        expected_base_domain_id=6,
    )
    assert result.is_valid is True
    assert result.plan_json["domain_name"] == "Enrollment"


def test_validator_remaps_dimension_key_when_column_name_is_unique() -> None:
    capabilities = _capabilities()
    capabilities["dimensions"] = [
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
    ]
    capabilities["time_columns"] = []
    capabilities["filter_columns"] = [
        {
            "column_key": "wt20.school_name",
            "label": "School Name",
            "data_type": "string",
            "filterable": True,
            "workspace_table_id": 20,
            "model_column_id": 99,
            "column_name": "school_name",
        }
    ]
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 6,
        "intent": "list",
        "selects": {"dimensions": [{"column_key": "wt34.lea_name"}], "metrics": []},
        "filters": [{"column_key": "wt34.school_name", "op": "equals", "value": "Barksdale Elementary"}],
        "time": {},
        "grouping": {"group_by": [], "order_by": []},
    }

    result = validate_and_repair_plan_v2(
        plan_json=plan,
        capabilities=capabilities,
        prompt="Show schools for Barksdale Elementary",
        expected_base_domain_id=6,
    )
    assert result.is_valid is True
    assert result.plan_json["selects"]["dimensions"][0]["column_key"] == "wt20.lea_name"
    assert result.plan_json["filters"][0]["column_key"] == "wt20.school_name"
    assert "remapped_dimension_column:wt34.lea_name->wt20.lea_name" in result.repairs_applied
    assert "remapped_filter_column:wt34.school_name->wt20.school_name" in result.repairs_applied


def test_validator_does_not_remap_when_column_name_is_ambiguous() -> None:
    capabilities = _capabilities()
    capabilities["dimensions"] = [
        {
            "column_key": "wt20.lea_name",
            "label": "LEA Name (School)",
            "data_type": "string",
            "filterable": True,
            "workspace_table_id": 20,
            "model_column_id": 266,
            "column_name": "lea_name",
        },
        {
            "column_key": "wt34.lea_name",
            "label": "LEA Name (ADM)",
            "data_type": "string",
            "filterable": True,
            "workspace_table_id": 34,
            "model_column_id": 9000,
            "column_name": "lea_name",
        },
    ]
    capabilities["time_columns"] = []
    capabilities["filter_columns"] = []
    plan = {
        "schema_version": 2,
        "trace_id": "t1",
        "workspace_id": "ws-1",
        "vertical_norm": "education",
        "base_domain_id": 6,
        "intent": "list",
        "selects": {"dimensions": [{"column_key": "wt99.lea_name"}], "metrics": []},
        "filters": [],
        "time": {},
        "grouping": {"group_by": [], "order_by": []},
    }

    result = validate_and_repair_plan_v2(
        plan_json=plan,
        capabilities=capabilities,
        prompt="Show LEA",
        expected_base_domain_id=6,
    )
    assert result.is_valid is False
    assert any(issue["code"] == "invalid_dimension_column" for issue in result.issues)
