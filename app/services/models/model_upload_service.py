from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

import pandas as pd
from werkzeug.datastructures import FileStorage

from app.exceptions.service_error import ServiceError
from app.services.models.model_write_service import ModelWriteService  # <-- confirm this path is correct

REQUIRED_COLUMNS = {"table_name", "column_name", "data_type", "description"}


@dataclass
class UploadError:
    rowNumber: int
    column: Optional[str]
    code: str
    message: str
    value: Optional[str] = None


@dataclass
class UploadResult:
    uploadId: str
    status: Literal["SUCCESS", "FAILED"]
    totalCount: int
    insertedTables: int
    insertedColumns: int
    updatedColumns: int
    deactivatedColumns: int
    errors: Optional[List[Dict[str, Any]]] = None


class ModelUploadService:
    """
    Excel/CSV -> model_table + model_column (MySQL)
    Dictionary is GLOBAL (not workspace-dependent).
    """

    def __init__(self, *, writer: Optional[ModelWriteService] = None):
        self._writer = writer or ModelWriteService()

    # ✅ this matches your route call
    def upload(
        self,
        *,
        workspace_id: str,            # accepted for route compatibility; not used
        user_id: Optional[str],       # accepted for route compatibility; not used
        file_storage: FileStorage,
        full_replace: bool = False,
        user_name: Optional[str] = None,  # preferred if you have it
    ) -> Dict[str, Any]:
        if file_storage is None:
            raise ServiceError("Missing file", status_code=400)

        filename = (file_storage.filename or "").strip()
        if not filename:
            raise ServiceError("Missing filename", status_code=400)

        file_bytes = file_storage.read()
        if not file_bytes:
            raise ServiceError("Empty file", status_code=400)

        # if caller doesn't pass a username, fall back to user_id or "unknown"
        uname = (user_name or user_id or "unknown").strip()

        result = self.handle_upload(
            file_bytes=file_bytes,
            filename=filename,
            user_name=uname,
            full_replace=bool(full_replace),
        )

        # return plain dict
        return result.__dict__

    # ---- your existing implementation below ----

    def handle_upload(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        user_name: str,
        full_replace: bool = False,
    ) -> UploadResult:
        try:
            df = self._read_file(file_bytes=file_bytes, filename=filename)
        except ValueError as e:
            raise ServiceError(str(e), status_code=400)

        df.columns = [self._norm_col(c) for c in df.columns]

        missing = REQUIRED_COLUMNS - set(df.columns)
        if missing:
            return self._fail(
                total=len(df),
                errors=[
                    UploadError(
                        rowNumber=0,
                        column=None,
                        code="MISSING_COLUMNS",
                        message=f"Missing required columns: {', '.join(sorted(missing))}",
                    )
                ],
            )

        for c in REQUIRED_COLUMNS:
            df[c] = df[c].astype(str).map(lambda x: (x or "").strip())

        errors: List[UploadError] = []
        rows: List[Dict[str, str]] = []

        for idx, row in df.iterrows():
            row_num = int(idx) + 2
            r = {k: (row.get(k) or "").strip() for k in REQUIRED_COLUMNS}

            for col in ("table_name", "column_name", "data_type"):
                if not r[col]:
                    errors.append(
                        UploadError(
                            rowNumber=row_num,
                            column=col,
                            code="REQUIRED",
                            message=f"{col} is required",
                        )
                    )

            if errors and len(errors) >= 2000:
                break

            rows.append(r)

        if errors:
            return self._fail(total=len(df), errors=errors)

        stats = self._writer.upsert_dictionary(
            user_name=user_name,
            rows=rows,
            full_replace=full_replace,
        )

        return UploadResult(
            uploadId=self._new_id(),
            status="SUCCESS",
            totalCount=len(rows),
            insertedTables=stats["inserted_tables"],
            insertedColumns=stats["inserted_columns"],
            updatedColumns=stats["updated_columns"],
            deactivatedColumns=stats["deactivated_columns"],
            errors=None,
        )

    def _read_file(self, *, file_bytes: bytes, filename: str) -> pd.DataFrame:
        lower = filename.lower()
        bio = io.BytesIO(file_bytes)

        if lower.endswith(".csv"):
            return pd.read_csv(bio, dtype=str, keep_default_na=False)
        if lower.endswith(".xlsx") or lower.endswith(".xls"):
            return pd.read_excel(bio, dtype=str, keep_default_na=False)

        raise ValueError("Unsupported file type (must be .csv or .xlsx)")

    def _norm_col(self, c: str) -> str:
        c = (c or "").strip().lower()
        c = re.sub(r"[^\w]+", "_", c)
        c = re.sub(r"_+", "_", c).strip("_")
        return c

    def _fail(self, *, total: int, errors: List[UploadError]) -> UploadResult:
        return UploadResult(
            uploadId=self._new_id(),
            status="FAILED",
            totalCount=total,
            insertedTables=0,
            insertedColumns=0,
            updatedColumns=0,
            deactivatedColumns=0,
            errors=[e.__dict__ for e in errors],
        )

    def _new_id(self) -> str:
        import uuid
        return uuid.uuid4().hex