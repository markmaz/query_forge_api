from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Dict, List

import pandas as pd

from app.exceptions.forge_error import ForgeError
from app.services.forge_match.normalizer import normalize_text

_HEADER_HINTS = {
    "source_field_name": {
        "field",
        "field name",
        "source field",
        "source field name",
        "column",
        "column name",
        "attribute",
        "element",
    },
    "source_description": {
        "description",
        "field description",
        "column description",
        "definition",
        "business definition",
    },
    "source_type": {"type", "data type", "datatype", "field type", "column type"},
    "source_object_name": {
        "table",
        "source table",
        "object",
        "entity",
        "source object",
        "source entity",
    },
    "sample_value": {"sample", "example", "sample value", "example value", "values"},
    "category": {"category", "group", "domain", "subject area"},
}


@dataclass(frozen=True)
class ParsedRow:
    row_number: int
    cells: Dict[str, str]


@dataclass(frozen=True)
class ParsedSheet:
    sheet_name: str
    header_row_index: int
    headers: List[str]
    rows: List[ParsedRow]


@dataclass(frozen=True)
class ParsedWorkbook:
    file_type: str
    sheets: List[ParsedSheet]


class ForgeMatchFileParser:
    def parse(self, *, file_bytes: bytes, filename: str) -> ParsedWorkbook:
        lower = str(filename or "").strip().lower()
        if lower.endswith(".csv"):
            sheet = self._parse_csv(file_bytes=file_bytes)
            return ParsedWorkbook(file_type="csv", sheets=[sheet])
        if lower.endswith(".xlsx") or lower.endswith(".xls"):
            return ParsedWorkbook(file_type="xlsx", sheets=self._parse_xlsx(file_bytes=file_bytes))
        raise ForgeError("Unsupported file type (must be .csv or .xlsx)", status_code=400)

    def _parse_csv(self, *, file_bytes: bytes) -> ParsedSheet:
        df = pd.read_csv(io.BytesIO(file_bytes), header=None, dtype=str, keep_default_na=False)
        return self._parse_sheet_df(sheet_name="Sheet1", df=df)

    def _parse_xlsx(self, *, file_bytes: bytes) -> List[ParsedSheet]:
        workbook = pd.read_excel(
            io.BytesIO(file_bytes),
            sheet_name=None,
            header=None,
            dtype=str,
            keep_default_na=False,
        )
        out: list[ParsedSheet] = []
        for sheet_name, df in workbook.items():
            if df is None:
                continue
            out.append(self._parse_sheet_df(sheet_name=str(sheet_name), df=df))
        return out

    def _parse_sheet_df(self, *, sheet_name: str, df: pd.DataFrame) -> ParsedSheet:
        if df.empty:
            return ParsedSheet(sheet_name=sheet_name, header_row_index=0, headers=[], rows=[])

        filled = df.fillna("")
        header_idx = self._detect_header_row(filled)
        raw_headers = [str(value or "").strip() for value in filled.iloc[header_idx].tolist()]
        headers = self._normalize_headers(raw_headers)

        rows: list[ParsedRow] = []
        for idx in range(header_idx + 1, len(filled.index)):
            values = [str(value or "").strip() for value in filled.iloc[idx].tolist()]
            if self._row_is_blank(values):
                continue
            row_map: dict[str, str] = {}
            for col_idx, header in enumerate(headers):
                row_map[header] = values[col_idx] if col_idx < len(values) else ""
            rows.append(ParsedRow(row_number=idx + 1, cells=row_map))

        return ParsedSheet(
            sheet_name=sheet_name,
            header_row_index=header_idx,
            headers=headers,
            rows=rows,
        )

    def _detect_header_row(self, df: pd.DataFrame) -> int:
        max_scan = min(25, len(df.index))
        best_idx = 0
        best_score = -1.0

        for idx in range(max_scan):
            raw_values = [str(value or "").strip() for value in df.iloc[idx].tolist()]
            score = self._header_score(raw_values)
            if score > best_score:
                best_score = score
                best_idx = idx

        if best_score < 1.5:
            return 0
        return best_idx

    def _header_score(self, cells: List[str]) -> float:
        if not cells:
            return 0.0
        score = 0.0
        seen_canon: set[str] = set()
        for cell in cells:
            norm = normalize_text(cell)
            if norm == "":
                continue
            for canonical, hints in _HEADER_HINTS.items():
                if norm in hints and canonical not in seen_canon:
                    score += 1.0
                    seen_canon.add(canonical)
                elif any(norm.startswith(h) for h in hints):
                    score += 0.4
        return score

    def _normalize_headers(self, raw_headers: List[str]) -> List[str]:
        out: list[str] = []
        used: set[str] = set()
        for idx, raw in enumerate(raw_headers):
            header = normalize_text(raw).replace(" ", "_")
            if header == "":
                header = f"col_{idx + 1}"
            base = header
            suffix = 2
            while header in used:
                header = f"{base}_{suffix}"
                suffix += 1
            used.add(header)
            out.append(header)
        return out

    @staticmethod
    def _row_is_blank(values: List[str]) -> bool:
        return all(str(value or "").strip() == "" for value in values)


__all__ = [
    "ForgeMatchFileParser",
    "ParsedWorkbook",
    "ParsedSheet",
    "ParsedRow",
]
