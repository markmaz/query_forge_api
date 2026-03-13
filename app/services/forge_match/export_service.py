from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort


class ForgeMatchExportService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def export_session(
        self,
        *,
        workspace_id: str,
        session_id: str,
        export_format: str,
    ) -> Tuple[bytes, str, str]:
        fmt = str(export_format or "").strip().lower()
        if fmt not in {"csv", "xlsx"}:
            raise ForgeError("format must be csv or xlsx", status_code=400)

        rows = self._load_export_rows(workspace_id=workspace_id, session_id=session_id)
        if fmt == "csv":
            return self._to_csv(rows, session_id=session_id)
        return self._to_xlsx(rows, session_id=session_id)

    def _load_export_rows(self, *, workspace_id: str, session_id: str) -> List[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              fr.id AS mapping_id,
              fsr.row_id,
              fsr.sheet_name,
              fsr.`row_number`,
              fsr.source_field_name,
              fsr.source_description,
              fsr.source_type,
              fsr.source_object_name,
              fsr.sample_value,
              fr.match_decision,
              fr.status,
              fr.confidence_score,
              fr.confidence_band,
              fr.explanation,
              fr.review_notes,
              fr.best_match_workspace_column_id,
              wc_best.column_name AS best_match_column_name,
              wt_best.table_name AS best_match_table_name,
              fr.manually_selected_workspace_column_id,
              wc_manual.column_name AS manual_column_name,
              wt_manual.table_name AS manual_table_name
            FROM forge_match_result fr
            JOIN forge_match_source_record fsr ON fsr.id = fr.source_record_id
            JOIN forge_match_session fms ON fms.id = fr.session_id
            LEFT JOIN workspace_column wc_best ON wc_best.id = fr.best_match_workspace_column_id
            LEFT JOIN workspace_table wt_best ON wt_best.id = wc_best.workspace_table_id
            LEFT JOIN workspace_column wc_manual ON wc_manual.id = fr.manually_selected_workspace_column_id
            LEFT JOIN workspace_table wt_manual ON wt_manual.id = wc_manual.workspace_table_id
            WHERE fr.session_id = :session_id
              AND fms.workspace_id = :workspace_id
            ORDER BY fsr.sheet_name ASC, fsr.`row_number` ASC
            """,
            {"workspace_id": workspace_id, "session_id": session_id},
        )
        return [self._json_safe_row(dict(row)) for row in rows]

    @staticmethod
    def _to_csv(rows: List[Dict[str, Any]], *, session_id: str) -> Tuple[bytes, str, str]:
        buffer = io.StringIO()
        columns = [
            "mapping_id",
            "row_id",
            "sheet_name",
            "row_number",
            "source_field_name",
            "source_description",
            "source_type",
            "source_object_name",
            "sample_value",
            "match_decision",
            "status",
            "confidence_score",
            "confidence_band",
            "best_match_workspace_column_id",
            "best_match_column_name",
            "best_match_table_name",
            "manually_selected_workspace_column_id",
            "manual_column_name",
            "manual_table_name",
            "explanation",
            "review_notes",
        ]
        writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

        return (
            buffer.getvalue().encode("utf-8"),
            "text/csv",
            f"forge_match_{session_id}.csv",
        )

    @staticmethod
    def _to_xlsx(rows: List[Dict[str, Any]], *, session_id: str) -> Tuple[bytes, str, str]:
        df = pd.DataFrame(rows)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Mappings", index=False)
        output.seek(0)
        return (
            output.read(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            f"forge_match_{session_id}.xlsx",
        )

    @staticmethod
    def _json_safe_row(row: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for key, value in row.items():
            if isinstance(value, (datetime, date)):
                out[key] = value.isoformat()
            else:
                out[key] = value
        return out


__all__ = ["ForgeMatchExportService"]
