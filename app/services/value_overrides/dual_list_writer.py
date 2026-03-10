from __future__ import annotations

from typing import Any, Dict, List, Literal, Mapping, Optional, Protocol, Sequence, Set, Tuple

from app.ports.sql_executor import ForgeQueryPort

# ---------------------------
# Shared types
# ---------------------------

ForgeSectionKey = Literal["regions", "npiCategories", "serviceLines"]

TABLE_BY_TYPE_DBX: dict[ForgeSectionKey, str] = {
    "regions": "workboard.custom_regions_lists",
    "npiCategories": "workboard.custom_npi_categories_lists",
    "serviceLines": "workboard.custom_service_lines_lists",
}

# ✅ MySQL physical tables (I prefer underscores; change if you want to keep exact names)
TABLE_BY_TYPE_MYSQL: dict[ForgeSectionKey, str] = {
    "regions": "workboard.custom_regions_lists",
    "npiCategories": "workboard.custom_npi_categories_lists",
    "serviceLines": "workboard.custom_service_lines_lists",
}

# Columns for inserts (Databricks keeps current shape).
COLUMNS_BY_TYPE_DBX: dict[ForgeSectionKey, List[str]] = {
    "regions": [
        "list_id", "workspace_id",
        "list_name", "user_name", "create_date", "expiration_date",
        "zipcode", "subregion", "region",
    ],
    "npiCategories": [
        "list_id", "workspace_id",
        "list_name", "user_name", "create_date", "expiration_date",
        "npi_type_code", "npi", "customer_npi_category_1", "customer_npi_category_2",
    ],
    "serviceLines": [
        "list_id", "workspace_id",
        "list_name", "user_name", "create_date", "expiration_date",
        "procedure_code", "customer_service_line", "customer_sub_service_line",
    ],
}

# MySQL includes user metadata + share flag for visibility.
COLUMNS_BY_TYPE_MYSQL: dict[ForgeSectionKey, List[str]] = {
    "regions": [
        "workspace_id",
        "list_name", "user_name", "user_id", "is_shared", "create_date", "expiration_date",
        "zipcode", "subregion", "region",
    ],
    "npiCategories": [
        "workspace_id",
        "list_name", "user_name", "user_id", "is_shared", "create_date", "expiration_date",
        "npi_type_code", "npi", "customer_npi_category_1", "customer_npi_category_2",
    ],
    "serviceLines": [
        "workspace_id",
        "list_name", "user_name", "user_id", "is_shared", "create_date", "expiration_date",
        "procedure_code", "customer_service_line", "customer_sub_service_line",
    ],
}

# ---------------------------
# Databricks DDL
# ---------------------------

DDL_BY_TYPE_DBX: dict[ForgeSectionKey, str] = {
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

# ---------------------------
# MySQL DDL (workspace_id + user_id + is_shared)
# ---------------------------

DDL_BY_TYPE_MYSQL: dict[ForgeSectionKey, str] = {
    "regions": """
CREATE TABLE IF NOT EXISTS workboard.custom_regions_lists (
  workspace_id VARCHAR(64) NOT NULL,
  list_name VARCHAR(255) NOT NULL,
  user_name VARCHAR(255) NULL,
  user_id VARCHAR(255) NULL,
  is_shared TINYINT(1) NOT NULL DEFAULT 0,
  create_date DATE NULL,
  expiration_date DATE NULL,
  zipcode VARCHAR(32) NOT NULL,
  subregion VARCHAR(255) NULL,
  region VARCHAR(255) NULL,

  PRIMARY KEY (workspace_id, list_name, zipcode),
  INDEX idx_regions_ws (workspace_id),
  INDEX idx_regions_ws_list (workspace_id, list_name),
  INDEX idx_regions_ws_user (workspace_id, user_id),
  INDEX idx_regions_ws_shared (workspace_id, is_shared)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
""".strip(),
    "npiCategories": """
CREATE TABLE IF NOT EXISTS workboard.custom_npi_categories_lists (
  workspace_id VARCHAR(64) NOT NULL,
  list_name VARCHAR(255) NOT NULL,
  user_name VARCHAR(255) NULL,
  user_id VARCHAR(255) NULL,
  is_shared TINYINT(1) NOT NULL DEFAULT 0,
  create_date DATE NULL,
  expiration_date DATE NULL,
  npi_type_code VARCHAR(8) NULL,
  npi VARCHAR(32) NOT NULL,
  customer_npi_category_1 VARCHAR(255) NULL,
  customer_npi_category_2 VARCHAR(255) NULL,

  PRIMARY KEY (workspace_id, list_name, npi),
  INDEX idx_npi_ws (workspace_id),
  INDEX idx_npi_ws_list (workspace_id, list_name),
  INDEX idx_npi_ws_user (workspace_id, user_id),
  INDEX idx_npi_ws_shared (workspace_id, is_shared)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
""".strip(),
    "serviceLines": """
CREATE TABLE IF NOT EXISTS workboard.custom_service_lines_lists (
  workspace_id VARCHAR(64) NOT NULL,
  list_name VARCHAR(255) NOT NULL,
  user_name VARCHAR(255) NULL,
  user_id VARCHAR(255) NULL,
  is_shared TINYINT(1) NOT NULL DEFAULT 0,
  create_date DATE NULL,
  expiration_date DATE NULL,
  procedure_code VARCHAR(64) NOT NULL,
  customer_service_line VARCHAR(255) NULL,
  customer_sub_service_line VARCHAR(255) NULL,

  PRIMARY KEY (workspace_id, list_name, procedure_code),
  INDEX idx_svc_ws (workspace_id),
  INDEX idx_svc_ws_list (workspace_id, list_name),
  INDEX idx_svc_ws_user (workspace_id, user_id),
  INDEX idx_svc_ws_shared (workspace_id, is_shared)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
""".strip(),
}

# ---------------------------
# Utilities
# ---------------------------

def _chunks(items: List[Any], n: int):
    for i in range(0, len(items), n):
        yield items[i : i + n]

def _forge_quote_dbx_table(table: str) -> str:
    return ".".join(f"`{p}`" for p in table.split("."))

def _forge_cols_sig(cols: Sequence[str]) -> set[str]:
    return {c.lower() for c in cols}

def _forge_column_type_dbx(name: str) -> str:
    if name in {"create_date", "expiration_date"}:
        return "DATE"
    return "STRING"

# ---------------------------
# Port / Protocol
# ---------------------------

class ForgeListWriterPort(Protocol):
    def ensure_tables(self) -> None: ...
    def insert_rows(self, list_type: ForgeSectionKey, rows: List[Dict[str, Any]]) -> int: ...

class ForgeDatabricksListWriter(ForgeListWriterPort):
    """
    Databricks SQL Statements API writer (chunked VALUES).
    Ensures tables exist and validates schema.
    """

    def __init__(self, sql: ForgeQueryPort, *, max_rows_per_chunk: int = 500):
        self._sql = sql
        self._chunk_size = max_rows_per_chunk
        self._ensured: Set[ForgeSectionKey] = set()

    def ensure_tables(self) -> None:
        for k in TABLE_BY_TYPE_DBX.keys():
            self._ensure_table(k)

    def ensure_table(self, list_type: ForgeSectionKey) -> None:
        self._ensure_table(list_type)

    def insert_rows(self, list_type: ForgeSectionKey, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0

        self._ensure_table(list_type)

        table = TABLE_BY_TYPE_DBX[list_type]
        cols = COLUMNS_BY_TYPE_DBX[list_type]

        total_inserted = 0
        for chunk in _chunks(rows, self._chunk_size):
            sql_text, params = self._forge_build_insert_dbx(table, cols, chunk)
            resp = self._sql.submit_statement(sql_text, parameters=params, qf_result_fmt="JSON_ARRAY")

            state = (resp.get("status") or {}).get("state")
            if state != "SUCCEEDED":
                raise RuntimeError(f"Databricks insert failed: {resp}")

            total_inserted += len(chunk)

        return total_inserted

    def _ensure_table(self, list_type: ForgeSectionKey) -> None:
        if list_type in self._ensured:
            return

        ddl = DDL_BY_TYPE_DBX[list_type]
        resp = self._sql.submit_statement(ddl, qf_result_fmt="JSON_ARRAY")
        state = (resp.get("status") or {}).get("state")
        if state != "SUCCEEDED":
            raise RuntimeError(f"Databricks CREATE TABLE failed: {resp}")

        self._validate_table_schema(list_type)
        self._ensured.add(list_type)

    def _validate_table_schema(self, list_type: ForgeSectionKey) -> None:
        table = TABLE_BY_TYPE_DBX[list_type]
        expected = _forge_cols_sig(COLUMNS_BY_TYPE_DBX[list_type])
        actual = self._forge_fetch_cols_dbx(table)

        missing = [c for c in expected if c not in actual]
        if missing:
            self._forge_add_missing_cols_dbx(table, missing)
            actual = self._forge_fetch_cols_dbx(table)
            missing = [c for c in expected if c not in actual]
            if missing:
                raise RuntimeError(
                    f"Table {table} missing required cols: {missing}. Actual: {sorted(actual)}"
                )

    def _forge_fetch_cols_dbx(self, table: str) -> set[str]:
        table_sql = _forge_quote_dbx_table(table)
        resp = self._sql.submit_statement(f"DESCRIBE TABLE {table_sql}", qf_result_fmt="JSON_ARRAY")

        state = (resp.get("status") or {}).get("state")
        if state != "SUCCEEDED":
            raise RuntimeError(f"DESCRIBE TABLE failed: {resp}")

        rows = resp.get("rows", [])
        cols: set[str] = set()

        for r in rows:
            col = None
            if isinstance(r, dict):
                col = r.get("col_name")
            elif isinstance(r, (list, tuple)) and len(r) > 0:
                col = r[0]

            if not col:
                continue
            col = str(col)
            if col.startswith("#"):
                continue

            cols.add(col.lower())

        return cols

    def _forge_add_missing_cols_dbx(self, table: str, missing: List[str]) -> None:
        table_sql = _forge_quote_dbx_table(table)
        cols_sql = ", ".join(f"`{c}` {_forge_column_type_dbx(c)}" for c in missing)
        sql = f"ALTER TABLE {table_sql} ADD COLUMNS ({cols_sql})"
        resp = self._sql.submit_statement(sql, qf_result_fmt="JSON_ARRAY")
        state = (resp.get("status") or {}).get("state")
        if state != "SUCCEEDED":
            raise RuntimeError(f"ALTER TABLE failed: {resp}")

    def _forge_build_insert_dbx(
        self,
        table: str,
        cols: Sequence[str],
        rows: Sequence[Mapping[str, Any]],
    ) -> Tuple[str, Dict[str, Any]]:
        for r in rows:
            for c in cols:
                if c not in r:
                    raise ValueError(f"Missing column '{c}' in row: {r}")

        params: Dict[str, Any] = {}
        values_sql_parts: List[str] = []

        for i, r in enumerate(rows):
            ph = []
            for c in cols:
                key = f"{c}_{i}"
                ph.append(f":{key}")
                params[key] = r[c]
            values_sql_parts.append("(" + ", ".join(ph) + ")")

        cols_sql = ", ".join(f"`{c}`" for c in cols)
        table_sql = _forge_quote_dbx_table(table)
        values_sql = ",\n  ".join(values_sql_parts)

        sql_text = f"""
            INSERT INTO {table_sql} ({cols_sql})
            SELECT * FROM VALUES
            {values_sql}
            AS t({cols_sql})
            """.strip()

        return sql_text, params


class ForgeMySQLListWriter(ForgeListWriterPort):
    """
    MySQL writer (chunked multi-row VALUES).
    Uses your SQLAlchemy transaction pattern via ForgeQueryPort.
    Ensures tables exist and validates schema via information_schema.
    """

    def __init__(self, mysql: ForgeQueryPort, *, max_rows_per_chunk: int = 1000):
        self._mysql = mysql
        self._chunk_size = max_rows_per_chunk
        self._ensured: Set[ForgeSectionKey] = set()

    def ensure_tables(self) -> None:
        for k in TABLE_BY_TYPE_MYSQL.keys():
            self._ensure_table(k)

    def insert_rows(self, list_type: ForgeSectionKey, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0

        self._ensure_table(list_type)

        table = TABLE_BY_TYPE_MYSQL[list_type]
        cols = COLUMNS_BY_TYPE_MYSQL[list_type]

        total = 0
        for chunk in _chunks(rows, self._chunk_size):
            sql_text, params = self._forge_build_insert_mysql(table, cols, chunk)
            self._mysql.execute_write(sql_text, params)
            # For INSERT, affected == inserted rows typically; but drivers vary with duplicates.
            total += len(chunk)
        return total

    def _ensure_table(self, list_type: ForgeSectionKey) -> None:
        if list_type in self._ensured:
            return

        ddl = DDL_BY_TYPE_MYSQL[list_type]
        self._mysql.execute_write(ddl)
        self._validate_table_schema(list_type)
        self._ensured.add(list_type)

    def _validate_table_schema(self, list_type: ForgeSectionKey) -> None:
        table_fq = TABLE_BY_TYPE_MYSQL[list_type]
        schema, table = self._forge_split_schema_table(table_fq)

        expected = _forge_cols_sig(COLUMNS_BY_TYPE_MYSQL[list_type])
        actual = self._forge_fetch_cols_mysql(schema, table)

        missing = [c for c in expected if c not in actual]
        if missing:
            raise RuntimeError(
                f"MySQL table {schema}.{table} missing required cols: {missing}. Actual: {sorted(actual)}"
            )

    def _forge_split_schema_table(self, fq: str) -> Tuple[str, str]:
        parts = fq.split(".")
        if len(parts) != 2:
            # default schema if user passes "table" only
            return ("workboard", fq)
        return (parts[0], parts[1])

    def _forge_fetch_cols_mysql(self, schema: str, table: str) -> set[str]:
        rows = self._mysql.execute_query_mappings(
            """
            SELECT COLUMN_NAME
            FROM information_schema.columns
            WHERE TABLE_SCHEMA = :schema AND TABLE_NAME = :table
            """.strip(),
            {"schema": schema, "table": table},
        )
        return {str(r["COLUMN_NAME"]).lower() for r in rows}

    def _forge_build_insert_mysql(
        self,
        table_fq: str,
        cols: Sequence[str],
        rows: Sequence[Mapping[str, Any]],
    ) -> Tuple[str, Dict[str, Any]]:
        for r in rows:
            for c in cols:
                if c not in r:
                    raise ValueError(f"Missing column '{c}' in row: {r}")

        params: Dict[str, Any] = {}
        values_sql_parts: List[str] = []

        for i, r in enumerate(rows):
            ph = []
            for c in cols:
                key = f"{c}_{i}"
                ph.append(f":{key}")
                params[key] = r[c]
            values_sql_parts.append("(" + ", ".join(ph) + ")")

        cols_sql = ", ".join(f"`{c}`" for c in cols)
        values_sql = ", ".join(values_sql_parts)

        # table_fq like "workboard.custom_regions_lists"
        schema, table = self._forge_split_schema_table(table_fq)
        table_sql = f"`{schema}`.`{table}`"

        sql_text = f"""
            INSERT INTO {table_sql} ({cols_sql})
            VALUES {values_sql}
            """.strip()

        return sql_text, params


class ForgeDualListWriter(ForgeListWriterPort):
    """
    Writes to MySQL first (fast UI source of truth), then best-effort to Databricks.
    You can choose whether Databricks failures should raise.
    """

    def __init__(
        self,
        mysql_writer: ForgeMySQLListWriter,
        dbx_writer: ForgeDatabricksListWriter,
        *,
        fail_if_dbx_fails: bool = False,
        on_dbx_error: Optional[callable] = None,
    ):
        self._mysql = mysql_writer
        self._dbx = dbx_writer
        self._fail_dbx = fail_if_dbx_fails
        self._on_dbx_error = on_dbx_error

    def ensure_tables(self) -> None:
        self._mysql.ensure_tables()
        self._dbx.ensure_tables()

    def insert_rows(self, list_type: ForgeSectionKey, rows: List[Dict[str, Any]]) -> int:
        inserted = self._mysql.insert_rows(list_type, rows)

        try:
            self._dbx.insert_rows(list_type, rows)
        except Exception as e:
            if self._on_dbx_error:
                try:
                    self._on_dbx_error(list_type, rows, e)
                except Exception:
                    pass
            if self._fail_dbx:
                raise

        return inserted
