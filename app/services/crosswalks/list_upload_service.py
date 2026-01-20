from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4

import pandas as pd

from app.services.crosswalks.crosswalk_meta_writer import CrosswalkMetaWriter

SectionKey = Literal["regions", "npiCategories", "serviceLines"]

ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")
DIGITS_RE = re.compile(r"^\d+$")

REQUIRED_COLUMNS: Dict[SectionKey, set[str]] = {
    "regions": {"zipcode", "subregion", "region"},
    "npiCategories": {"npi_type_code", "npi", "customer_npi_category_1", "customer_npi_category_2"},
    "serviceLines": {"procedure_code", "customer_service_line", "customer_sub_service_line"},
}

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
    inferredType: SectionKey
    status: Literal["SUCCESS", "FAILED"]
    insertedCount: int
    totalCount: int
    listId: Optional[str] = None
    listName: Optional[str] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None
    owner: Optional[str] = None
    userId: Optional[str] = None
    isShared: Optional[bool] = None
    errors: Optional[List[Dict[str, Any]]] = None


class ListUploadService:
    def __init__(self, db_writer: Any, meta_writer: Optional[CrosswalkMetaWriter] = None):
        """
        db_writer: your adapter that can write rows to Databricks (Delta table insert, COPY INTO, etc.)
        """
        self._db = db_writer
        self._meta = meta_writer

    def handle_upload(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        list_name: str,
        user_name: str,
        workspace_id: str,
        user_id: str,
        is_shared: bool = False,
        expected_type: Optional[SectionKey] = None,   # ✅ NEW
    ) -> UploadResult:
        # 1) parse
        df = self._read_file(file_bytes=file_bytes, filename=filename)

        # 2) normalize headers
        df.columns = [self._norm_col(c) for c in df.columns]

        # 3) infer type
        inferred = self._infer_type(set(df.columns))

        # ✅ 3b) enforce type (if provided)
        if expected_type and inferred != expected_type:
            return self._fail(
                inferred,  # keep inferred in payload so UI can show what it detected
                total=len(df),
                errors=[
                    UploadError(
                        rowNumber=0,
                        column=None,
                        code="TYPE_MISMATCH",
                        message=(
                            f"Upload target type '{expected_type}' does not match detected type '{inferred}'. "
                            "Please download the correct template or upload to the correct section."
                        ),
                    )
                ],
            )

        # 4) validate columns
        missing = REQUIRED_COLUMNS[inferred] - set(df.columns)
        if missing:
            return self._fail(inferred, total=len(df), errors=[
                UploadError(
                    rowNumber=0,
                    column=None,
                    code="MISSING_COLUMNS",
                    message=f"Missing required columns: {', '.join(sorted(missing))}",
                )
            ])

        # 5) validate rows
        errors: List[UploadError] = []
        total = len(df)

        # Keep values as strings where appropriate
        df = self._coerce_types(df, inferred)

        for idx, row in df.iterrows():
            row_num = int(idx) + 2
            errors.extend(self._validate_row(inferred, row_num, row.to_dict()))
            if len(errors) >= 2000:
                break

        if errors:
            return self._fail(inferred, total=total, errors=errors)

        # 6) enrich + insert (ALL-OR-NOTHING)
        create_date = date.today()
        expiration_date = create_date + timedelta(days=90)
        list_id = str(uuid4())

        enriched_rows = []
        for _, row in df.iterrows():
            r = row.to_dict()
            r["list_id"] = list_id
            r["workspace_id"] = workspace_id
            r["list_name"] = list_name.strip()
            r["user_name"] = user_name
            r["create_date"] = create_date.isoformat()
            r["expiration_date"] = expiration_date.isoformat()
            enriched_rows.append(r)

        ensure_table = getattr(self._db, "ensure_table", None)
        if callable(ensure_table):
            ensure_table(inferred)
        inserted = self._db.insert_rows(inferred, enriched_rows)

        if self._meta:
            self._meta.upsert_meta(
                workspace_id=workspace_id,
                list_type=inferred,
                list_id=list_id,
                list_name=list_name.strip(),
                user_id=user_id,
                user_name=user_name,
                is_shared=is_shared,
            )

        return UploadResult(
            uploadId=self._new_id(),
            inferredType=inferred,
            status="SUCCESS",
            insertedCount=inserted,
            totalCount=total,
            listId=list_id,
            listName=list_name.strip(),
            createdAt=create_date.isoformat(),
            updatedAt=create_date.isoformat(),
            owner=user_name,
            userId=user_id,
            isShared=bool(is_shared),
            errors=None,
        )
    # ---------- helpers ----------

    def _read_file(self, *, file_bytes: bytes, filename: str) -> pd.DataFrame:
        lower = filename.lower()
        bio = io.BytesIO(file_bytes)

        if lower.endswith(".csv"):
            # keep as strings; prevent "00123" losing zeros
            return pd.read_csv(bio, dtype=str, keep_default_na=False)
        if lower.endswith(".xlsx") or lower.endswith(".xls"):
            # read first sheet; keep strings
            return pd.read_excel(bio, dtype=str, keep_default_na=False)

        raise ValueError("Unsupported file type (must be .csv or .xlsx)")

    def _norm_col(self, c: str) -> str:
        # normalize "Customer Service Line" => "customer_service_line"
        c = (c or "").strip().lower()
        c = re.sub(r"[^\w]+", "_", c)
        c = re.sub(r"_+", "_", c).strip("_")
        return c

    def _infer_type(self, cols: set[str]) -> SectionKey:
        matches = [t for t, req in REQUIRED_COLUMNS.items() if req.issubset(cols)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) == 0:
            raise ValueError(f"Could not infer list type from columns: {sorted(cols)}")
        raise ValueError(f"Ambiguous list type; matches: {matches}")

    def _coerce_types(self, df: pd.DataFrame, inferred: SectionKey) -> pd.DataFrame:
        # ensure string trims
        for col in REQUIRED_COLUMNS[inferred]:
            df[col] = df[col].astype(str).map(lambda x: x.strip())
        return df

    def _validate_row(self, inferred: SectionKey, row_num: int, r: Dict[str, Any]) -> List[UploadError]:
        errs: List[UploadError] = []

        def req(col: str) -> str:
            v = (r.get(col) or "").strip()
            if v == "":
                errs.append(UploadError(rowNumber=row_num, column=col, code="REQUIRED", message=f"{col} is required"))
            return v

        if inferred == "regions":
            z = req("zipcode")
            if z and not ZIP_RE.match(z):
                errs.append(UploadError(rowNumber=row_num, column="zipcode", code="INVALID_ZIP", message="Invalid ZIP code", value=z))

            req("subregion")
            req("region")

        elif inferred == "npiCategories":
            t = req("npi_type_code")
            if t and t not in ("1", "2"):
                errs.append(UploadError(rowNumber=row_num, column="npi_type_code", code="INVALID_TYPE", message="Must be 1 or 2", value=t))

            npi = req("npi")
            if npi:
                if not (len(npi) == 10 and DIGITS_RE.match(npi)):
                    errs.append(UploadError(rowNumber=row_num, column="npi", code="INVALID_NPI", message="NPI must be 10 digits", value=npi))
                elif not self._luhn_ok(npi):
                    errs.append(UploadError(rowNumber=row_num, column="npi", code="INVALID_NPI_LUHN", message="NPI failed checksum", value=npi))

            # categories: decide your rule; here we allow blanks but require at least one
            c1 = (r.get("customer_npi_category_1") or "").strip()
            c2 = (r.get("customer_npi_category_2") or "").strip()
            if not c1 and not c2:
                errs.append(UploadError(rowNumber=row_num, column=None, code="CATEGORY_REQUIRED", message="At least one customer_npi_category must be provided"))

        else:  # serviceLines
            req("procedure_code")
            req("customer_service_line")
            # sub service line optional? change to req(...) if required
            _ = (r.get("customer_sub_service_line") or "").strip()

        return errs

    def _luhn_ok(self, n: str) -> bool:
        # Standard Luhn checksum
        digits = [int(ch) for ch in n]
        checksum = 0
        parity = len(digits) % 2
        for i, d in enumerate(digits):
            if i % 2 == parity:
                d *= 2
                if d > 9:
                    d -= 9
            checksum += d
        return checksum % 10 == 0

    def _fail(self, inferred: SectionKey, *, total: int, errors: List[UploadError]) -> UploadResult:
        return UploadResult(
            uploadId=self._new_id(),
            inferredType=inferred,
            status="FAILED",
            insertedCount=0,
            totalCount=total,
            errors=[e.__dict__ for e in errors],
        )

    def _new_id(self) -> str:
        # replace with nanoid/uuid if you want
        import uuid
        return uuid.uuid4().hex
