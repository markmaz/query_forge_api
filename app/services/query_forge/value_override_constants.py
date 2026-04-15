from __future__ import annotations

VALUE_OVERRIDE_KEY_BY_TYPE = {
    "regions": "zipcode",
    "npiCategories": "npi",
    "serviceLines": "procedure_code",
}

VALUE_OVERRIDE_JOIN_ALIAS_BY_TYPE = {
    "regions": "cw_regions",
    "npiCategories": "cw_npi",
    "serviceLines": "cw_sl",
}

VALUE_OVERRIDE_FIELDS_BY_TYPE = {
    "regions": ["region", "subregion"],
    "npiCategories": ["npi_type_code", "customer_npi_category_1", "customer_npi_category_2"],
    "serviceLines": ["customer_service_line", "customer_sub_service_line"],
}

VALUE_OVERRIDE_PROJECT_ALIASES_BY_TYPE = {
    "regions": {
        "region": "cw_region",
        "subregion": "cw_subregion",
    },
    "npiCategories": {
        "npi_type_code": "cw_npi_type_code",
        "customer_npi_category_1": "cw_npi_category_1",
        "customer_npi_category_2": "cw_npi_category_2",
    },
    "serviceLines": {
        "customer_service_line": "cw_service_line",
        "customer_sub_service_line": "cw_sub_service_line",
    },
}
