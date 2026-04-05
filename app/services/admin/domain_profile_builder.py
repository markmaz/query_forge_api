from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort

_DOMAIN_QUERY = """
SELECT
  d.id AS domain_id,
  d.workspace_id,
  d.name AS domain_name,
  d.description AS domain_description,
  d.kind AS domain_kind,
  d.is_active AS domain_is_active
FROM domain d
WHERE d.workspace_id = :workspace_id
  AND d.id = :domain_id
LIMIT 1
"""

_TABLES_QUERY = """
SELECT
  dwt.domain_id,
  dwt.workspace_table_id,
  dwt.role,
  dwt.is_primary,
  dwt.relation_kind,
  dwt.sort_order,
  dwt.table_alias,
  dwt.filter_mode,
  dwt.cardinality,
  wt.table_name,
  wt.full_name,
  wt.catalog_name,
  wt.schema_name,
  wt.variant_code,
  wt.exists_in_dbx,
  wt.source_table_name,
  wt.description AS table_description
FROM domain_workspace_table dwt
JOIN domain d
  ON d.id = dwt.domain_id
 AND d.workspace_id = :workspace_id
JOIN workspace_table wt
  ON wt.id = dwt.workspace_table_id
WHERE dwt.domain_id = :domain_id
ORDER BY dwt.is_primary DESC, dwt.sort_order ASC, dwt.workspace_table_id ASC
"""

_COLUMNS_QUERY = """
SELECT
  wc.workspace_table_id,
  wc.column_name,
  wc.data_type,
  wc.nullable,
  wc.ordinal_position,
  wc.semantic_type,
  COALESCE(wc.description, '') AS description
FROM domain_workspace_table dwt
JOIN domain d
  ON d.id = dwt.domain_id
 AND d.workspace_id = :workspace_id
JOIN workspace_table wt
  ON wt.id = dwt.workspace_table_id
JOIN workspace_column wc
  ON wc.workspace_table_id = wt.id
WHERE dwt.domain_id = :domain_id
ORDER BY wc.workspace_table_id ASC, wc.ordinal_position ASC, wc.column_name ASC
"""

_JOINS_QUERY = """
SELECT
  dtj.id,
  dtj.domain_id,
  dtj.from_workspace_table_id,
  dtj.to_workspace_table_id,
  dtj.join_type,
  dtj.join_spec_json,
  dtj.sort_order,
  dtj.is_active,
  wf.table_name AS from_table_name,
  wt.table_name AS to_table_name
FROM domain_table_join dtj
JOIN domain d
  ON d.id = dtj.domain_id
 AND d.workspace_id = :workspace_id
LEFT JOIN workspace_table wf
  ON wf.id = dtj.from_workspace_table_id
LEFT JOIN workspace_table wt
  ON wt.id = dtj.to_workspace_table_id
WHERE dtj.domain_id = :domain_id
  AND dtj.is_active = 1
ORDER BY dtj.sort_order ASC, dtj.created_at ASC
"""


class DomainProfileBuilder:
    """Loads complete domain context used by LLM profile generation."""

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def build_domain_context(self, *, workspace_id: str, domain_id: int) -> Dict[str, Any]:
        workspace = str(workspace_id or "").strip()
        if not workspace:
            raise ForgeError("workspace_id is required", status_code=400)
        did = int(domain_id)

        params = {"workspace_id": workspace, "domain_id": did}
        domain_rows = self._sql.execute_query_mappings(_DOMAIN_QUERY, params)
        if not domain_rows:
            raise ForgeError(
                "Domain not found",
                status_code=404,
                details={"workspace_id": workspace, "domain_id": did},
            )
        domain = dict(domain_rows[0])

        table_rows = [dict(row) for row in self._sql.execute_query_mappings(_TABLES_QUERY, params)]
        column_rows = [dict(row) for row in self._sql.execute_query_mappings(_COLUMNS_QUERY, params)]
        join_rows = [dict(row) for row in self._sql.execute_query_mappings(_JOINS_QUERY, params)]

        tables_by_id: Dict[int, Dict[str, Any]] = {}
        for row in table_rows:
            table_id = int(row.get("workspace_table_id") or 0)
            tables_by_id[table_id] = {
                "workspace_table_id": table_id,
                "table_name": str(row.get("table_name") or "").strip(),
                "full_name": str(row.get("full_name") or "").strip(),
                "catalog_name": str(row.get("catalog_name") or "").strip() or None,
                "schema_name": str(row.get("schema_name") or "").strip() or None,
                "source_table_name": str(row.get("source_table_name") or "").strip() or None,
                "description": str(row.get("table_description") or "").strip() or None,
                "role": str(row.get("role") or "").strip() or None,
                "is_primary": bool(row.get("is_primary")),
                "relation_kind": str(row.get("relation_kind") or "").strip() or None,
                "sort_order": int(row.get("sort_order") or 0),
                "table_alias": str(row.get("table_alias") or "").strip() or None,
                "filter_mode": str(row.get("filter_mode") or "").strip() or None,
                "cardinality": str(row.get("cardinality") or "").strip() or None,
                "exists_in_dbx": bool(row.get("exists_in_dbx")),
                "columns": [],
            }

        for row in column_rows:
            table_id = int(row.get("workspace_table_id") or 0)
            table = tables_by_id.get(table_id)
            if table is None:
                continue
            table["columns"].append(
                {
                    "column_name": str(row.get("column_name") or "").strip(),
                    "data_type": str(row.get("data_type") or "").strip() or None,
                    "description": str(row.get("description") or "").strip() or None,
                    "semantic_type": str(row.get("semantic_type") or "").strip() or None,
                    "nullable": bool(row.get("nullable")),
                    "ordinal_position": int(row.get("ordinal_position") or 0),
                }
            )

        joins: List[Dict[str, Any]] = []
        for row in join_rows:
            raw_spec = row.get("join_spec_json")
            join_spec = _parse_json(raw_spec)
            joins.append(
                {
                    "join_id": str(row.get("id") or ""),
                    "from_workspace_table_id": int(row.get("from_workspace_table_id") or 0),
                    "to_workspace_table_id": int(row.get("to_workspace_table_id") or 0),
                    "from_table_name": str(row.get("from_table_name") or "").strip() or None,
                    "to_table_name": str(row.get("to_table_name") or "").strip() or None,
                    "join_type": str(row.get("join_type") or "LEFT").strip().upper(),
                    "join_spec": join_spec if isinstance(join_spec, dict) else {},
                    "sort_order": int(row.get("sort_order") or 0),
                }
            )

        table_list = sorted(
            tables_by_id.values(),
            key=lambda item: (
                0 if bool(item.get("is_primary")) else 1,
                int(item.get("sort_order") or 0),
                str(item.get("table_name") or ""),
            ),
        )
        relationship_lines = _build_relationship_lines(table_map=tables_by_id, joins=joins)

        return {
            "workspace_id": workspace,
            "domain": {
                "domain_id": int(domain.get("domain_id") or did),
                "name": str(domain.get("domain_name") or "").strip(),
                "description": str(domain.get("domain_description") or "").strip() or None,
                "kind": str(domain.get("domain_kind") or "").strip() or None,
                "is_active": bool(domain.get("domain_is_active")),
            },
            "tables": table_list,
            "joins": joins,
            "relationship_lines": relationship_lines,
            "stats": {
                "table_count": len(table_list),
                "column_count": sum(len(table.get("columns") or []) for table in table_list),
                "join_count": len(joins),
            },
        }


def _parse_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _build_relationship_lines(*, table_map: Dict[int, Dict[str, Any]], joins: List[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    for join in joins:
        from_id = int(join.get("from_workspace_table_id") or 0)
        to_id = int(join.get("to_workspace_table_id") or 0)
        from_name = str(
            join.get("from_table_name")
            or (table_map.get(from_id) or {}).get("table_name")
            or f"wt{from_id}"
        ).strip()
        to_name = str(
            join.get("to_table_name")
            or (table_map.get(to_id) or {}).get("table_name")
            or f"wt{to_id}"
        ).strip()
        join_type = str(join.get("join_type") or "LEFT").strip().upper()
        spec = join.get("join_spec") if isinstance(join.get("join_spec"), dict) else {}
        on_clause = _join_on_clause(spec)
        line = f"{from_name} {join_type} JOIN {to_name} ON {on_clause}"
        lines.append(line)
    return lines


def _join_on_clause(join_spec: Dict[str, Any]) -> str:
    clauses = join_spec.get("clauses")
    if not isinstance(clauses, list) or not clauses:
        return "(join conditions unspecified)"
    fragments: List[str] = []
    for clause in clauses:
        if not isinstance(clause, dict):
            continue
        left = str(clause.get("left") or "").strip()
        op = str(clause.get("op") or "=").strip() or "="
        right = str(clause.get("right") or "").strip()
        if not left or not right:
            continue
        fragments.append(f"{left} {op} {right}")
    return " AND ".join(fragments) if fragments else "(join conditions unspecified)"


__all__ = ["DomainProfileBuilder"]
