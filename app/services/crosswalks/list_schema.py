# app/services/lists/list_schema.py
from __future__ import annotations

from typing import Dict, List

from app.models.crosswalk import ColumnSpec, SectionKey

TABLE_BY_TYPE: Dict[SectionKey, str] = {
    "regions": "workboard.custom_regions_lists",
    "npiCategories": "workboard.custom_npi_categories_lists",
    "serviceLines": "workboard.custom_service_lines_lists",
}

# Columns users care about in preview (exclude system/meta columns)
DATA_COLUMNS_BY_TYPE: Dict[SectionKey, List[ColumnSpec]] = {
    "regions": [
        ColumnSpec(name="zipcode", type="string", comment="primary geographic key"),
        ColumnSpec(name="subregion", type="string", comment="custom subregion tied to zipcode"),
        ColumnSpec(name="region", type="string", comment="custom region tied to zipcode"),
    ],
    "npiCategories": [
        ColumnSpec(name="npi_type_code", type="string", comment="1=individual, 2=organization"),
        ColumnSpec(name="npi", type="string", comment="10-digit NPI"),
        ColumnSpec(name="customer_npi_category_1", type="string"),
        ColumnSpec(name="customer_npi_category_2", type="string"),
    ],
    "serviceLines": [
        ColumnSpec(name="procedure_code", type="string", comment="procedure code"),
        ColumnSpec(name="customer_service_line", type="string"),
        ColumnSpec(name="customer_sub_service_line", type="string"),
    ],
}