from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Literal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

TemplateType = Literal["regions", "npiCategories", "serviceLines"]

HEADER_FILL = PatternFill(start_color="F3F4F6", end_color="F3F4F6", fill_type="solid")
HEADER_FONT = Font(bold=True)
HEADER_ALIGN = Alignment(horizontal="left", vertical="center")

TEMPLATES: Dict[str, Dict[str, List[str]]] = {
  "regions": {
    "base_filename": "regions_template",
    "columns": ["zipcode", "subregion", "region"],
  },
  "npiCategories": {
    "base_filename": "npi_categories_template",
    "columns": ["npi_type_code", "npi", "customer_npi_category_1", "customer_npi_category_2"],
  },
  "serviceLines": {
    "base_filename": "service_lines_template",
    "columns": ["procedure_code", "customer_service_line", "customer_sub_service_line"],
  },
}

NOTES: Dict[str, List[str]] = {
    "regions": [
        "zipcode: recommended 5-digit ZIP (keep as text).",
        "subregion/region: your custom groupings tied to zipcode.",
    ],
    "npiCategories": [
        "npi_type_code: 1 = individual, 2 = organization (dropdown provided).",
        "npi: must be 10 digits (keep as text).",
    ],
    "serviceLines": [
        "procedure_code: your procedure code (keep as text).",
    ],
}


@dataclass(frozen=True)
class TemplateFile:
    filename: str
    content_type: str
    bytes: bytes


class ListTemplateService:
    CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def generate_template(self, template_type: TemplateType, *, include_time: bool = False) -> TemplateFile:
        if template_type not in TEMPLATES:
            raise ValueError(f"Unknown template_type '{template_type}'")

        wb = self._build_workbook(template_type)
        data = self._workbook_to_bytes(wb)

        now = datetime.now(timezone.utc)
        suffix = now.strftime("%Y-%m-%d_%H%M") if include_time else now.strftime("%Y-%m-%d")
        base = TEMPLATES[template_type]["base_filename"]
        filename = f"{base}_{suffix}.xlsx"

        return TemplateFile(filename=filename, content_type=self.CONTENT_TYPE, bytes=data)

    def _build_workbook(self, template_type: TemplateType) -> Workbook:
        cfg = TEMPLATES[template_type]
        cols = cfg["columns"]

        wb = Workbook()
        ws = wb.active
        ws.title = "Template"

        # Header
        ws.append(cols)
        for i, col_name in enumerate(cols, start=1):
            c = ws.cell(row=1, column=i)
            c.font = HEADER_FONT
            c.fill = HEADER_FILL
            c.alignment = HEADER_ALIGN

        ws.freeze_panes = "A2"

        # Column widths
        for i, col_name in enumerate(cols, start=1):
            width = max(14, min(38, len(col_name) + 4))
            ws.column_dimensions[self._col_letter(i)].width = width

        # Instructions sheet
        inst = wb.create_sheet("Instructions")
        inst["A1"] = "How to use this template"
        inst["A1"].font = Font(bold=True, size=12)

        inst["A3"] = "1) Fill in the columns on the Template tab."
        inst["A4"] = "2) Do not change the header names."
        inst["A5"] = "3) Upload the file back to the application."

        inst["A7"] = "Notes"
        inst["A7"].font = Font(bold=True)

        for idx, line in enumerate(NOTES.get(template_type, []), start=8):
            inst[f"A{idx}"] = f"- {line}"

        inst.column_dimensions["A"].width = 100

        # Data validation: npi_type_code dropdown
        if template_type == "npiCategories":
            dv = DataValidation(type="list", formula1='"1,2"', allow_blank=False, showDropDown=True)
            dv.error = "Invalid value. Choose 1 (individual) or 2 (organization)."
            dv.errorTitle = "Invalid npi_type_code"
            dv.prompt = "Choose: 1 = individual, 2 = organization"
            dv.promptTitle = "npi_type_code"

            npi_type_idx = cols.index("npi_type_code") + 1
            col_letter = self._col_letter(npi_type_idx)
            dv.ranges.add(f"{col_letter}2:{col_letter}5000")
            ws.add_data_validation(dv)

        return wb

    def _workbook_to_bytes(self, wb: Workbook) -> bytes:
        bio = io.BytesIO()
        wb.save(bio)
        bio.seek(0)
        return bio.getvalue()

    def _col_letter(self, n: int) -> str:
        s = ""
        while n:
            n, r = divmod(n - 1, 26)
            s = chr(65 + r) + s
        return s