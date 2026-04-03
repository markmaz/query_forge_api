from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SnapshotResult:
    ok: bool
    workspace_id: str
    qf_catalog_name: str
    qf_schema_name: str
    run_id: str
    ran_at_utc: str
    tables_seen: int
    columns_seen: int


@dataclass(frozen=True)
class TableStage:
    full_name: str
    qf_catalog_name: str
    qf_schema_name: str
    qf_table_name: str
    qf_variant_code: Optional[str]
    is_qe: int


@dataclass(frozen=True)
class ColumnStage:
    full_name: str
    column_name: str
    data_type: str
    nullable: int
    qf_ordinal_position: int
