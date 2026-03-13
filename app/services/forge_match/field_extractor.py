from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from app.services.forge_match.file_parser import ParsedWorkbook
from app.services.forge_match.normalizer import looks_like_field_name, normalize_text

_FIELD_KEYS = {
    "source_field_name",
    "field_name",
    "source_field",
    "column_name",
    "column",
    "attribute",
    "element",
    "name",
}
_DESC_KEYS = {
    "source_description",
    "description",
    "field_description",
    "column_description",
    "definition",
}
_TYPE_KEYS = {"source_type", "type", "data_type", "datatype", "field_type", "column_type"}
_OBJECT_KEYS = {"source_object_name", "table", "source_table", "object", "entity", "source_object"}
_SAMPLE_KEYS = {"sample_value", "sample", "example", "example_value", "sample_values", "values"}
_CATEGORY_KEYS = {"category", "group", "subject_area", "domain"}


@dataclass(frozen=True)
class SourceFieldRecord:
    row_id: str
    sheet_name: str
    row_number: int
    source_field_name: str
    source_description: Optional[str]
    source_type: Optional[str]
    source_object_name: Optional[str]
    sample_value: Optional[str]
    category: Optional[str]
    normalized_search_text: str
    raw_row: Dict[str, str]


class ForgeMatchFieldExtractor:
    def extract(self, *, workbook: ParsedWorkbook) -> List[SourceFieldRecord]:
        out: list[SourceFieldRecord] = []
        for sheet in workbook.sheets:
            for row in sheet.rows:
                record = self._extract_row(sheet_name=sheet.sheet_name, row_number=row.row_number, row=row.cells)
                if record is not None:
                    out.append(record)
        return out

    def _extract_row(self, *, sheet_name: str, row_number: int, row: Dict[str, str]) -> Optional[SourceFieldRecord]:
        field = self._pick_first(row, _FIELD_KEYS)
        if not field:
            field = self._fallback_field_name(row)
        if not field:
            return None
        if not looks_like_field_name(field):
            return None

        description = self._pick_first(row, _DESC_KEYS)
        source_type = self._pick_first(row, _TYPE_KEYS)
        source_object = self._pick_first(row, _OBJECT_KEYS)
        sample = self._pick_first(row, _SAMPLE_KEYS)
        category = self._pick_first(row, _CATEGORY_KEYS)

        # Skip obvious junk and section header rows.
        if normalize_text(field) in {"field", "field_name", "column", "name", "description"}:
            return None

        row_id = f"{sheet_name}:{row_number}"
        search_text = self._build_search_text(
            source_field_name=field,
            source_description=description,
            source_type=source_type,
            source_object_name=source_object,
            sample_value=sample,
        )

        return SourceFieldRecord(
            row_id=row_id,
            sheet_name=sheet_name,
            row_number=row_number,
            source_field_name=field,
            source_description=description,
            source_type=source_type,
            source_object_name=source_object,
            sample_value=sample,
            category=category,
            normalized_search_text=search_text,
            raw_row={k: str(v or "") for k, v in row.items()},
        )

    @staticmethod
    def _pick_first(row: Dict[str, str], aliases: Sequence[str]) -> Optional[str]:
        alias_set = {normalize_text(a).replace(" ", "_") for a in aliases}
        for key, value in row.items():
            key_norm = normalize_text(key).replace(" ", "_")
            if key_norm in alias_set:
                text = str(value or "").strip()
                if text:
                    return text
        return None

    @staticmethod
    def _fallback_field_name(row: Dict[str, str]) -> Optional[str]:
        for _, value in row.items():
            text = str(value or "").strip()
            if not text:
                continue
            if looks_like_field_name(text):
                return text
        return None

    @staticmethod
    def _build_search_text(
        *,
        source_field_name: str,
        source_description: Optional[str],
        source_type: Optional[str],
        source_object_name: Optional[str],
        sample_value: Optional[str],
    ) -> str:
        parts = [str(source_field_name or "").strip()]
        if source_description:
            parts.append(str(source_description).strip())
        if source_type:
            parts.append(f"Type: {str(source_type).strip()}")
        if source_object_name:
            parts.append(f"Object: {str(source_object_name).strip()}")
        if sample_value:
            parts.append(f"Sample: {str(sample_value).strip()}")
        return ". ".join(p for p in parts if p)


__all__ = ["ForgeMatchFieldExtractor", "SourceFieldRecord"]
