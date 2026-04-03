from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from app.services.workspace_inventory.workspace_snapshot_discovery import is_qe_from_variant, split_base_and_variant
from app.services.workspace_inventory.workspace_snapshot_models import ColumnStage, TableStage


def stage_snapshot_rows(
    rows: List[Dict[str, Any]],
    accepted_bases: Set[str],
) -> Tuple[List[TableStage], List[ColumnStage], Set[str]]:
    table_by_full: Dict[str, TableStage] = {}
    columns: List[ColumnStage] = []
    seen_bases: Set[str] = set()

    for row in rows:
        qf_catalog_name = str(row["qf_catalog_name"])
        qf_schema_name = str(row["qf_schema_name"])
        physical_table = str(row["qf_table_name"])
        full_name = f"{qf_catalog_name}.{qf_schema_name}.{physical_table}"

        base_name, qf_variant_code = split_base_and_variant(physical_table, accepted_bases)
        seen_bases.add(base_name)

        table_by_full.setdefault(
            full_name,
            TableStage(
                full_name=full_name,
                qf_catalog_name=qf_catalog_name,
                qf_schema_name=qf_schema_name,
                qf_table_name=base_name,
                qf_variant_code=qf_variant_code,
                is_qe=1 if is_qe_from_variant(qf_variant_code) else 0,
            ),
        )

        columns.append(
            ColumnStage(
                full_name=full_name,
                column_name=str(row["column_name"]),
                data_type=str(row["data_type"]),
                nullable=1 if str(row["is_nullable"]).upper() == "YES" else 0,
                qf_ordinal_position=int(row["qf_ordinal_position"]),
            )
        )

    return list(table_by_full.values()), columns, seen_bases
