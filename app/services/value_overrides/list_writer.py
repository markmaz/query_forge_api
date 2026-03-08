from __future__ import annotations

from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Set, Tuple

from app.ports.sql_executor import ForgeQueryPort

ForgeSectionKey = Literal["regions", "npiCategories", "serviceLines"]

TABLE_BY_TYPE: dict[ForgeSectionKey, str] = {
    "regions": "workboard.custom_regions_lists",
    "npiCategories": "workboard.custom_npi_categories_lists",
    "serviceLines": "workboard.custom_service_lines_lists",
}

COLUMNS_BY_TYPE: dict[ForgeSectionKey, List[str]] = {
    "regions": [
        "list_id", "workspace_id", "list_name", "user_name", "create_date", "expiration_date",
        "zipcode", "subregion", "region",
    ],
    "npiCategories": [
        "list_id", "workspace_id", "list_name", "user_name", "create_date", "expiration_date",
        "npi_type_code", "npi", "customer_npi_category_1", "customer_npi_category_2",
    ],
    "serviceLines": [
        "list_id", "workspace_id", "list_name", "user_name", "create_date", "expiration_date",
        "procedure_code", "customer_service_line", "customer_sub_service_line",
    ],
}

DDL_BY_TYPE: dict[ForgeSectionKey, str] = {
    "regions": """
CREATE TABLE IF NOT EXISTS workboard.custom_regions_lists (
  list_id STRING COMMENT 'stable list UUID',
  workspace_id STRING COMMENT 'Databricks workspace id',
  list_name STRING COMMENT 'Name of custom list',
  user_name STRING COMMENT 'Name of user creating the custom list',
  create_date DATE COMMENT 'set to current_date()',
  expiration_date DATE COMMENT 'set to date_add(current_date(), 90)',
  zipcode STRING COMMENT 'primary geographic key',
  subregion STRING COMMENT 'custom subregion tied to zipcode',
  region STRING COMMENT 'custom region tied to zipcode'
)
USING DELTA
""".strip(),
    "npiCategories": """
CREATE TABLE IF NOT EXISTS workboard.custom_npi_categories_lists (
  list_id STRING COMMENT 'stable list UUID',
  workspace_id STRING COMMENT 'Databricks workspace id',
  list_name STRING,
  user_name STRING,
  create_date DATE,
  expiration_date DATE,
  npi_type_code STRING COMMENT '1=individual, 2=organization',
  npi STRING COMMENT '10-digit NPI',
  customer_npi_category_1 STRING,
  customer_npi_category_2 STRING
)
USING DELTA
""".strip(),
    "serviceLines": """
CREATE TABLE IF NOT EXISTS workboard.custom_service_lines_lists (
  list_id STRING COMMENT 'stable list UUID',
  workspace_id STRING COMMENT 'Databricks workspace id',
  list_name STRING,
  user_name STRING,
  create_date DATE,
  expiration_date DATE,
  procedure_code STRING COMMENT 'procedure code',
  customer_service_line STRING,
  customer_sub_service_line STRING
)
USING DELTA
""".strip(),
}


class ForgeListWriter:
    """
    Inserts rows into tables via the SQL Statements API (bulk VALUES, chunked).
    Ensures the destination table exists before inserting and validates schema.
    """

    def __init__(self, sql: ForgeQueryPort, *, max_rows_per_chunk: int = 500):
        self._sql = sql
        self._chunk_size = max_rows_per_chunk
        self._ensured: Set[ForgeSectionKey] = set()

    def insert_rows(self, list_type: ForgeSectionKey, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0

        # ✅ ensure + validate table schema before inserting
        self._ensure_table(list_type)

        table = TABLE_BY_TYPE[list_type]
        cols = COLUMNS_BY_TYPE[list_type]
        max_rows = max(1, 256 // max(1, len(cols)))
        chunk_size = min(self._chunk_size, max_rows)

        total_inserted = 0
        for chunk in _chunks(rows, chunk_size):
            sql_text, params = self._build_insert_values(table, cols, chunk)
            resp = self._sql.submit_statement(sql_text, parameters=params, qf_result_fmt="JSON_ARRAY")

            state = (resp.get("status") or {}).get("state")
            if state != "SUCCEEDED":
                raise RuntimeError(f"Databricks insert failed: {resp}")

            total_inserted += len(chunk)

        return total_inserted

    def ensure_table(self, list_type: ForgeSectionKey) -> None:
        self._ensure_table(list_type)

    def _ensure_table(self, list_type: ForgeSectionKey) -> None:
        if list_type in self._ensured:
            return

        ddl = DDL_BY_TYPE[list_type]
        resp = self._sql.submit_statement(ddl, qf_result_fmt="JSON_ARRAY")

        state = (resp.get("status") or {}).get("state")
        if state != "SUCCEEDED":
            raise RuntimeError(f"Databricks CREATE TABLE failed: {resp}")

        self._validate_table_schema(list_type)

        self._ensured.add(list_type)

    def _validate_table_schema(self, list_type: ForgeSectionKey) -> None:
        table = TABLE_BY_TYPE[list_type]
        expected_cols = COLUMNS_BY_TYPE[list_type]

        actual_cols = self._forge_fetch_table_cols(table)

        missing = [c for c in expected_cols if c.lower() not in actual_cols]
        if missing:
            self._forge_add_missing_cols(table, missing)
            actual_cols = self._forge_fetch_table_cols(table)
            missing = [c for c in expected_cols if c.lower() not in actual_cols]
            if missing:
                raise RuntimeError(
                    f"Table {table} is missing required columns: {missing}. "
                    f"Expected at least: {expected_cols}. "
                    f"Actual: {sorted(actual_cols.keys())}"
                )

    def _forge_fetch_table_cols(self, table: str) -> Dict[str, str]:
        """
        Returns {column_name_lower: data_type_lower} for a Databricks table using DESCRIBE TABLE.

        Handles both:
          - dict rows: {"col_name": "...", "data_type": "...", "comment": "..."}
          - array rows: ["...", "...", "..."]
        """
        table_sql = ".".join(f"`{p}`" for p in table.split("."))

        resp = self._sql.submit_statement(
            f"DESCRIBE TABLE {table_sql}",
            qf_result_fmt="JSON_ARRAY",
        )

        state = (resp.get("status") or {}).get("state")
        if state != "SUCCEEDED":
            raise RuntimeError(f"DESCRIBE TABLE failed: {resp}")

        rows = resp.get("rows", [])
        schema: Dict[str, str] = {}

        for r in rows:
            col, dtype = self._forge_row_to_col_type(r)
            if not col:
                continue

            if col.startswith("#"):
                continue

            schema[col.lower()] = (dtype or "").lower()

        return schema

    def _forge_add_missing_cols(self, table: str, missing: list[str]) -> None:
        table_sql = ".".join(f"`{p}`" for p in table.split("."))
        cols_sql = ", ".join(f"`{c}` {_forge_column_type(c)}" for c in missing)
        sql = f"ALTER TABLE {table_sql} ADD COLUMNS ({cols_sql})"
        resp = self._sql.submit_statement(sql, qf_result_fmt="JSON_ARRAY")
        state = (resp.get("status") or {}).get("state")
        if state != "SUCCEEDED":
            raise RuntimeError(f"ALTER TABLE failed: {resp}")


    def _forge_row_to_col_type(self, r: Any) -> tuple[Optional[str], Optional[str]]:
        """
        Normalize a single DESCRIBE TABLE row into (col_name, data_type).
        """
        if isinstance(r, dict):
            col = r.get("col_name")
            dtype = r.get("data_type")
            return (str(col) if col is not None else None, str(dtype) if dtype is not None else None)

        if isinstance(r, (list, tuple)):
            # Databricks typically returns [col_name, data_type, comment]
            col = r[0] if len(r) > 0 else None
            dtype = r[1] if len(r) > 1 else None
            return (str(col) if col is not None else None, str(dtype) if dtype is not None else None)

        return (None, None)

    def _build_insert_values(
        self,
        table: str,
        cols: Sequence[str],
        rows: Sequence[Mapping[str, Any]],
    ) -> Tuple[str, Dict[str, Any]]:
        # Ensure required columns exist in every row
        for r in rows:
            for c in cols:
                if c not in r:
                    raise ValueError(f"Missing column '{c}' in row: {r}")

        values_sql_parts: List[str] = []
        params: Dict[str, Any] = {}

        for i, r in enumerate(rows):
            ph = []
            for c in cols:
                key = f"{c}_{i}"
                ph.append(f":{key}")
                params[key] = r[c]
            values_sql_parts.append("(" + ", ".join(ph) + ")")

        # Backtick identifiers for safety
        cols_sql = ", ".join(f"`{c}`" for c in cols)
        table_sql = ".".join(f"`{p}`" for p in table.split("."))

        values_sql = ",\n  ".join(values_sql_parts)

        sql_text = f"""
INSERT INTO {table_sql} ({cols_sql})
SELECT * FROM VALUES
  {values_sql}
AS t({cols_sql})
""".strip()

        return sql_text, params


def _chunks(items: List[Any], n: int):
    for i in range(0, len(items), n):
        yield items[i : i + n]


def _forge_column_type(name: str) -> str:
    if name in {"create_date", "expiration_date"}:
        return "DATE"
    return "STRING"
