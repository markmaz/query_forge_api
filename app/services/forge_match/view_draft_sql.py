from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Sequence

from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.domain_resolver import DomainPlan, DomainPlanJoin, DomainResolver

_SQL_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ForgeMatchViewDraftBuilder:
    def __init__(
        self,
        *,
        sql: ForgeQueryPort,
        resolver_factory: Callable[[str], DomainResolver],
    ) -> None:
        self._sql = sql
        self._resolver_factory = resolver_factory

    def build_view_draft_sql_preview(
        self,
        *,
        workspace_id: str,
        session_id: str,
        draft_name: str,
        accepted_columns: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        view_name = _normalize_sql_identifier(draft_name, fallback=f"forge_match_view_{session_id[:8]}")
        involved_tables = self.collect_involved_tables(accepted_columns)
        suspected_keys_by_table = self.load_suspected_table_keys(
            workspace_id=workspace_id,
            involved_tables=involved_tables,
        )
        if not accepted_columns:
            return {
                "view_name": view_name,
                "base_table_name": None,
                "is_executable": False,
                "blocking_reason": "No accepted mappings are available for this session.",
                "select_sql": None,
                "create_view_sql": None,
                "editable_sql": None,
                "join_domain_id": None,
                "join_domain_name": None,
                "involved_tables": [],
            }

        table_ids = sorted(
            {
                int(row.get("workspace_table_id") or 0)
                for row in accepted_columns
                if int(row.get("workspace_table_id") or 0) > 0
            }
        )
        if not table_ids:
            return {
                "view_name": view_name,
                "base_table_name": None,
                "is_executable": False,
                "blocking_reason": "Accepted mappings do not resolve to workspace tables.",
                "select_sql": None,
                "create_view_sql": None,
                "editable_sql": None,
                "join_domain_id": None,
                "join_domain_name": None,
                "involved_tables": involved_tables,
            }

        select_sql = None
        base_table_name = None
        join_domain_id = None
        join_domain_name = None
        blocking_reason = None

        if len(table_ids) == 1:
            base_table_name = str(accepted_columns[0].get("full_name") or "").strip() or None
            if not base_table_name:
                blocking_reason = "Accepted mappings do not have a resolvable base table name."
            else:
                table_alias = _build_table_alias_map_for_rows(accepted_columns).get(table_ids[0], "src")
                select_sql = self.compile_single_table_select_sql(
                    full_name=base_table_name,
                    table_alias=table_alias,
                    accepted_columns=accepted_columns,
                )
        else:
            join_resolution = self.resolve_joinable_domain_for_tables(
                workspace_id=workspace_id,
                workspace_table_ids=table_ids,
            )
            if join_resolution is None:
                blocking_reason = (
                    "Accepted mappings span multiple tables with no resolvable shared domain join path."
                )
            else:
                join_domain_id = int(join_resolution["domain_id"])
                join_domain_name = str(join_resolution["domain_name"] or "").strip() or None
                base_table_name = str(join_resolution["plan"].primary.full_name)
                select_sql = self.compile_multi_table_select_sql(
                    plan=join_resolution["plan"],
                    resolver=join_resolution["resolver"],
                    required_table_ids=table_ids,
                    accepted_columns=accepted_columns,
                )

        create_view_sql = None
        comment_block = self.build_view_draft_comment_block(
            involved_tables=involved_tables,
            suspected_keys_by_table=suspected_keys_by_table,
            blocking_reason=blocking_reason,
            require_join_note=len(involved_tables) > 1 and not select_sql,
        )
        if select_sql:
            create_view_sql = f"{comment_block}CREATE VIEW {_quote_identifier(view_name)} AS\n{select_sql};"

        editable_sql = create_view_sql
        if editable_sql is None:
            editable_sql = self.compile_unresolved_join_sql_template(
                view_name=view_name,
                accepted_columns=accepted_columns,
                involved_tables=involved_tables,
                comment_block=comment_block,
            )

        return {
            "view_name": view_name,
            "base_table_name": base_table_name,
            "is_executable": bool(create_view_sql),
            "blocking_reason": blocking_reason,
            "select_sql": select_sql,
            "create_view_sql": create_view_sql,
            "editable_sql": editable_sql,
            "join_domain_id": join_domain_id,
            "join_domain_name": join_domain_name,
            "involved_tables": involved_tables,
        }

    @staticmethod
    def collect_involved_tables(accepted_columns: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen: set[int] = set()
        tables: List[Dict[str, Any]] = []
        for row in accepted_columns:
            workspace_table_id = int(row.get("workspace_table_id") or 0)
            if workspace_table_id <= 0 or workspace_table_id in seen:
                continue
            seen.add(workspace_table_id)
            tables.append(
                {
                    "workspace_table_id": workspace_table_id,
                    "table_name": row.get("table_name"),
                    "full_name": row.get("full_name"),
                }
            )
        return tables

    def load_suspected_table_keys(
        self,
        *,
        workspace_id: str,
        involved_tables: Sequence[Dict[str, Any]],
    ) -> Dict[int, List[str]]:
        table_ids = sorted(
            {
                int(row.get("workspace_table_id") or 0)
                for row in involved_tables
                if int(row.get("workspace_table_id") or 0) > 0
            }
        )
        if not table_ids:
            return {}

        placeholders = ", ".join(f":wt_{idx}" for idx, _ in enumerate(table_ids))
        params: Dict[str, Any] = {"workspace_id": workspace_id}
        for idx, workspace_table_id in enumerate(table_ids):
            params[f"wt_{idx}"] = int(workspace_table_id)

        rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              wc.workspace_table_id,
              wc.column_name,
              wc.description
            FROM workspace_column wc
            JOIN workspace_table wt ON wt.id = wc.workspace_table_id
            WHERE wt.workspace_id = :workspace_id
              AND wc.workspace_table_id IN ({placeholders})
            """,
            params,
        )

        scored: Dict[int, List[tuple[int, str]]] = {}
        for row in rows:
            workspace_table_id = int(row.get("workspace_table_id") or 0)
            column_name = str(row.get("column_name") or "").strip()
            if workspace_table_id <= 0 or not column_name:
                continue
            score = _score_suspected_key_column(
                column_name=column_name,
                description=row.get("description"),
            )
            if score <= 0:
                continue
            scored.setdefault(workspace_table_id, []).append((score, column_name))

        output: Dict[int, List[str]] = {}
        for workspace_table_id, candidates in scored.items():
            names: List[str] = []
            seen: set[str] = set()
            for _, column_name in sorted(candidates, key=lambda item: (-item[0], item[1])):
                if column_name in seen:
                    continue
                seen.add(column_name)
                names.append(column_name)
                if len(names) >= 4:
                    break
            if names:
                output[workspace_table_id] = names
        return output

    def build_view_draft_comment_block(
        self,
        *,
        involved_tables: Sequence[Dict[str, Any]],
        suspected_keys_by_table: Dict[int, List[str]],
        blocking_reason: Optional[str],
        require_join_note: bool,
    ) -> str:
        comments: List[str] = []
        if blocking_reason:
            comments.append(f"-- {blocking_reason}")
        if involved_tables:
            comments.append("-- Involved tables:")
            for row in involved_tables:
                workspace_table_id = int(row.get("workspace_table_id") or 0)
                table_label = str(row.get("full_name") or row.get("table_name") or "").strip()
                if not table_label:
                    continue
                suspected_keys = suspected_keys_by_table.get(workspace_table_id) or []
                suffix = f" (suspected keys: {', '.join(suspected_keys)})" if suspected_keys else ""
                comments.append(f"-- - {table_label}{suffix}")
        if require_join_note:
            comments.append("-- Add the required JOIN clauses before running this SQL.")
        return "\n".join(comments) + ("\n\n" if comments else "")

    def resolve_joinable_domain_for_tables(
        self,
        *,
        workspace_id: str,
        workspace_table_ids: Sequence[int],
    ) -> Optional[Dict[str, Any]]:
        if not workspace_table_ids:
            return None
        placeholders = ", ".join(f":wt_{idx}" for idx, _ in enumerate(workspace_table_ids))
        params: Dict[str, Any] = {"workspace_id": workspace_id, "required_count": len(workspace_table_ids)}
        for idx, workspace_table_id in enumerate(workspace_table_ids):
            params[f"wt_{idx}"] = int(workspace_table_id)

        candidate_rows = self._sql.execute_query_mappings(
            f"""
            SELECT
              d.id AS domain_id,
              d.name AS domain_name,
              COUNT(DISTINCT dwt.workspace_table_id) AS matched_table_count,
              COUNT(*) AS total_table_count
            FROM domain d
            JOIN domain_workspace_table dwt
              ON dwt.domain_id = d.id
            WHERE d.workspace_id = :workspace_id
              AND d.is_active = 1
              AND dwt.workspace_table_id IN ({placeholders})
            GROUP BY d.id, d.name
            HAVING COUNT(DISTINCT dwt.workspace_table_id) = :required_count
            ORDER BY total_table_count ASC, d.id ASC
            """,
            params,
        )

        for row in candidate_rows:
            domain_id = int(row.get("domain_id") or 0)
            if domain_id <= 0:
                continue
            resolver = self._resolver_factory(workspace_id)
            try:
                plan = resolver.resolve_plan(domain_id)
                alias_by_workspace_table_id = _build_table_alias_map_for_plan(plan)
                self.compile_domain_from_clause(
                    plan=plan,
                    resolver=resolver,
                    required_table_ids=workspace_table_ids,
                    alias_by_workspace_table_id=alias_by_workspace_table_id,
                )
            except ForgeError:
                continue
            return {
                "domain_id": domain_id,
                "domain_name": row.get("domain_name"),
                "resolver": resolver,
                "plan": plan,
            }
        return None

    def compile_single_table_select_sql(
        self,
        *,
        full_name: str,
        table_alias: str,
        accepted_columns: Sequence[Dict[str, Any]],
    ) -> str:
        alias = _quote_identifier(table_alias)
        select_lines = self.compile_select_list(
            accepted_columns=accepted_columns,
            alias_by_workspace_table_id={
                int(accepted_columns[0].get("workspace_table_id") or 0): table_alias,
            },
        )
        return (
            "SELECT\n"
            f"{select_lines}\n"
            f"FROM {_quote_fqn(full_name)} {alias}"
        )

    def compile_multi_table_select_sql(
        self,
        *,
        plan: DomainPlan,
        resolver: DomainResolver,
        required_table_ids: Sequence[int],
        accepted_columns: Sequence[Dict[str, Any]],
    ) -> str:
        alias_by_workspace_table_id = _build_table_alias_map_for_plan(plan)
        from_clause = self.compile_domain_from_clause(
            plan=plan,
            resolver=resolver,
            required_table_ids=required_table_ids,
            alias_by_workspace_table_id=alias_by_workspace_table_id,
        )
        select_lines = self.compile_select_list(
            accepted_columns=accepted_columns,
            alias_by_workspace_table_id=alias_by_workspace_table_id,
        )
        return (
            "SELECT\n"
            f"{select_lines}\n"
            f"FROM {from_clause}"
        )

    def compile_select_list(
        self,
        *,
        accepted_columns: Sequence[Dict[str, Any]],
        alias_by_workspace_table_id: Dict[int, str],
    ) -> str:
        seen_aliases: set[str] = set()
        lines: List[str] = []
        for row in accepted_columns:
            workspace_table_id = int(row.get("workspace_table_id") or 0)
            column_name = _required_text(row.get("column_name"), "column_name")
            table_alias = alias_by_workspace_table_id.get(workspace_table_id)
            if not table_alias:
                raise ForgeError("Accepted column table is not in the resolved SQL plan", status_code=400)
            output_alias = _normalize_sql_identifier(
                row.get("source_field_name"),
                fallback=f"column_{len(lines) + 1}",
                seen=seen_aliases,
            )
            lines.append(
                f"  {_quote_identifier(table_alias)}.{_quote_identifier(column_name)} AS {_quote_identifier(output_alias)}"
            )
        return ",\n".join(lines)

    def compile_domain_from_clause(
        self,
        *,
        plan: DomainPlan,
        resolver: DomainResolver,
        required_table_ids: Sequence[int],
        alias_by_workspace_table_id: Dict[int, str],
    ) -> str:
        tables_by_id = {int(table.workspace_table_id): table for table in plan.tables}
        needed_edges: Dict[tuple[str, int, int], DomainPlanJoin] = {}
        for workspace_table_id in required_table_ids:
            target_id = int(workspace_table_id)
            if target_id == int(plan.primary.workspace_table_id):
                continue
            for edge in resolver.get_join_path(plan, target_id):
                key = (str(edge.join_id), int(edge.from_workspace_table_id), int(edge.to_workspace_table_id))
                needed_edges[key] = edge

        joined = {int(plan.primary.workspace_table_id)}
        primary_alias = alias_by_workspace_table_id.get(int(plan.primary.workspace_table_id))
        if not primary_alias:
            raise ForgeError("Primary table alias is missing from the SQL plan", status_code=400)
        clauses = [f"{_quote_fqn(plan.primary.full_name)} {_quote_identifier(primary_alias)}"]
        remaining_edges = sorted(
            needed_edges.values(),
            key=lambda edge: (int(getattr(edge, "sort_order", 0)), str(edge.join_id)),
        )

        while remaining_edges:
            progress = False
            deferred: List[DomainPlanJoin] = []
            for edge in remaining_edges:
                from_id = int(edge.from_workspace_table_id)
                to_id = int(edge.to_workspace_table_id)
                if from_id == to_id:
                    raise ForgeError("Join cannot reference the same table", status_code=400)
                if from_id not in tables_by_id or to_id not in tables_by_id:
                    raise ForgeError("Join references table not in domain", status_code=400)
                if from_id not in joined:
                    deferred.append(edge)
                    continue

                join_type = str(edge.join_type or "").upper()
                if join_type not in {"INNER", "LEFT", "RIGHT"}:
                    raise ForgeError(f"Invalid join_type: {join_type}", status_code=400)

                to_table = tables_by_id[to_id]
                to_alias = alias_by_workspace_table_id.get(to_id)
                if not to_alias:
                    raise ForgeError("Join table alias is missing from the SQL plan", status_code=400)
                on_sql = self.compile_join_on(edge=edge, alias_by_wt=alias_by_workspace_table_id)
                clauses.append(
                    f"{join_type} JOIN {_quote_fqn(to_table.full_name)} {_quote_identifier(to_alias)} ON {on_sql}"
                )
                joined.add(to_id)
                progress = True

            if progress:
                remaining_edges = deferred
                continue
            raise ForgeError("Join order invalid: from table not yet joined", status_code=400)

        missing = [table_id for table_id in required_table_ids if int(table_id) not in joined]
        if missing:
            raise ForgeError("Domain join plan does not cover all required tables", status_code=400)
        return "\n".join(clauses)

    def compile_join_on(self, *, edge: DomainPlanJoin, alias_by_wt: Dict[int, str]) -> str:
        from_alias = alias_by_wt.get(int(edge.from_workspace_table_id))
        to_alias = alias_by_wt.get(int(edge.to_workspace_table_id))
        if not from_alias or not to_alias:
            raise ForgeError("Join references table not in domain", status_code=400)
        return " AND ".join(
            self.join_predicates(edge=edge, from_alias=from_alias, to_alias=to_alias)
        )

    def join_predicates(
        self,
        *,
        edge: DomainPlanJoin,
        from_alias: str,
        to_alias: str,
    ) -> List[str]:
        spec = edge.join_spec or {}
        on_list = spec.get("on") or []
        if not isinstance(on_list, list) or not on_list:
            raise ForgeError("Join spec must include a non-empty on[] list", status_code=400)

        predicates: List[str] = []
        for item in on_list:
            if not isinstance(item, dict):
                raise ForgeError("Join spec on[] must contain objects", status_code=400)

            left = item.get("left") or {}
            right = item.get("right") or {}
            left_wt = left.get("workspaceTableId")
            right_wt = right.get("workspaceTableId")
            if left_wt is not None and int(left_wt) != int(edge.from_workspace_table_id):
                raise ForgeError("Join spec left.workspaceTableId must match from table", status_code=400)
            if right_wt is not None and int(right_wt) != int(edge.to_workspace_table_id):
                raise ForgeError("Join spec right.workspaceTableId must match to table", status_code=400)

            left_expr = self.compile_join_side(left, expected_scope="from", alias=from_alias)
            right_expr = self.compile_join_side(right, expected_scope="to", alias=to_alias)
            predicates.append(f"{left_expr} = {right_expr}")
        return predicates

    def compile_join_side(self, side: Dict[str, Any], *, expected_scope: str, alias: str) -> str:
        expr = side.get("expr")
        if expr:
            scope, column_name, key = parse_join_expr(str(expr))
            if scope != expected_scope:
                raise ForgeError("Join spec expr uses wrong table scope", status_code=400)
            return f"get_json_object({_quote_identifier(alias)}.{_quote_identifier(column_name)}, '$.{key}')"

        column_name = side.get("columnName") or side.get("col")
        if not isinstance(column_name, str) or "." in column_name or not column_name.strip():
            raise ForgeError("Join spec column invalid", status_code=400)
        return f"{_quote_identifier(alias)}.{_quote_identifier(column_name)}"

    def compile_unresolved_join_sql_template(
        self,
        *,
        view_name: str,
        accepted_columns: Sequence[Dict[str, Any]],
        involved_tables: Sequence[Dict[str, Any]],
        comment_block: str,
    ) -> str:
        table_aliases = _build_table_alias_map_for_rows(involved_tables)
        primary_table = next(
            (row for row in involved_tables if str(row.get("full_name") or "").strip()),
            None,
        )
        primary_alias = (
            table_aliases.get(int(primary_table.get("workspace_table_id") or 0), "src")
            if primary_table
            else "src"
        )
        base_from = (
            f"{_quote_fqn(primary_table.get('full_name'))} {_quote_identifier(primary_alias)}"
            if primary_table
            else "`<table>` `src`"
        )

        seen_aliases: set[str] = set()
        select_lines: List[str] = []
        for row in accepted_columns:
            column_name = str(row.get("column_name") or "").strip()
            if not column_name:
                continue
            workspace_table_id = int(row.get("workspace_table_id") or 0)
            table_alias = table_aliases.get(workspace_table_id, primary_alias if primary_table else "src")
            output_alias = _normalize_sql_identifier(
                row.get("source_field_name"),
                fallback=column_name,
                seen=seen_aliases,
            )
            select_lines.append(
                f"  {_quote_identifier(table_alias)}.{_quote_identifier(column_name)} AS {_quote_identifier(output_alias)}"
            )

        select_clause = ",\n".join(select_lines) if select_lines else "  -- add accepted columns here"
        return (
            f"{comment_block}CREATE VIEW {_quote_identifier(view_name)} AS\n"
            "SELECT\n"
            f"{select_clause}\n"
            f"FROM {base_from}\n"
            ";"
        )


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if text == "":
        raise ForgeError(f"{field} is required", status_code=400)
    return text


def _require_sql_identifier(value: Any, *, field: str = "identifier") -> str:
    text = str(value or "").strip()
    if not text or not _SQL_IDENT.match(text):
        raise ForgeError(f"Unsafe SQL {field}: {text or '<empty>'}", status_code=400)
    return text


def _quote_identifier(value: Any) -> str:
    return f"`{_require_sql_identifier(value)}`"


def _quote_fqn(full_name: Any) -> str:
    text = str(full_name or "").strip()
    parts = text.split(".")
    if len(parts) not in (2, 3):
        raise ForgeError("Invalid fully qualified table name", status_code=400)
    return ".".join(_quote_identifier(part) for part in parts)


def _normalize_sql_identifier(
    value: Any,
    *,
    fallback: str,
    seen: Optional[set[str]] = None,
) -> str:
    raw = str(value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9_]+", "_", raw).strip("_")
    if normalized == "":
        normalized = fallback
    if normalized and normalized[0].isdigit():
        normalized = f"col_{normalized}"
    normalized = re.sub(r"_+", "_", normalized)
    if not _SQL_IDENT.match(normalized):
        normalized = re.sub(r"[^a-z0-9_]+", "_", fallback.lower()).strip("_") or "draft_view"
        if normalized[0].isdigit():
            normalized = f"col_{normalized}"
    if seen is None:
        return normalized
    candidate = normalized
    suffix = 2
    while candidate in seen:
        candidate = f"{normalized}_{suffix}"
        suffix += 1
    seen.add(candidate)
    return candidate


def _build_table_alias_map_for_rows(rows: Sequence[Dict[str, Any]]) -> Dict[int, str]:
    seen_aliases: set[str] = set()
    aliases: Dict[int, str] = {}
    for row in rows:
        workspace_table_id = int(row.get("workspace_table_id") or 0)
        if workspace_table_id <= 0 or workspace_table_id in aliases:
            continue
        aliases[workspace_table_id] = _make_table_alias(
            table_name=row.get("table_name"),
            full_name=row.get("full_name"),
            workspace_table_id=workspace_table_id,
            seen=seen_aliases,
        )
    return aliases


def _build_table_alias_map_for_plan(plan: DomainPlan) -> Dict[int, str]:
    seen_aliases: set[str] = set()
    aliases: Dict[int, str] = {}
    for table in plan.tables:
        workspace_table_id = int(getattr(table, "workspace_table_id", 0) or 0)
        if workspace_table_id <= 0 or workspace_table_id in aliases:
            continue
        aliases[workspace_table_id] = _make_table_alias(
            table_name=getattr(table, "table_name", None),
            full_name=getattr(table, "full_name", None),
            workspace_table_id=workspace_table_id,
            seen=seen_aliases,
        )
    return aliases


def _make_table_alias(
    *,
    table_name: Any,
    full_name: Any,
    workspace_table_id: int,
    seen: set[str],
) -> str:
    base_name = str(table_name or "").strip()
    if not base_name:
        full_name_text = str(full_name or "").strip()
        if full_name_text:
            base_name = full_name_text.split(".")[-1].strip()
    return _normalize_sql_identifier(
        base_name,
        fallback=f"table_{int(workspace_table_id)}",
        seen=seen,
    )


def _score_suspected_key_column(*, column_name: Any, description: Any) -> int:
    name = str(column_name or "").strip().lower()
    desc = str(description or "").strip().lower()
    if not name:
        return 0

    score = 0
    if name in {"id", "pk"}:
        score += 10
    if name.startswith("k_"):
        score += 9
    if name.endswith("_id") or name.endswith("_key"):
        score += 7
    if "_id_" in name or "_key_" in name:
        score += 5
    if "foreign key" in desc:
        score += 8
    if "primary key" in desc:
        score += 8
    if "natural key" in desc:
        score += 7
    if "surrogate" in desc:
        score += 6
    if "identifier" in desc or "identifying" in desc:
        score += 5
    if "used to join" in desc or "join to" in desc or "join key" in desc:
        score += 5
    if "foreign" in desc and "key" in desc:
        score += 4
    if "primary" in desc and "key" in desc:
        score += 4
    if " key " in f" {desc} ":
        score += 3
    return score


def _normalize_optional_sql_identifier(value: Any, *, field: str) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    return _require_sql_identifier(text, field=field)


def normalize_optional_sql_identifier(value: Any, *, field: str) -> Optional[str]:
    return _normalize_optional_sql_identifier(value, field=field)


def _canonicalize_sql(sql: str) -> str:
    out = str(sql or "")
    out = re.sub(r"/\*.*?\*/", " ", out, flags=re.DOTALL)
    out = re.sub(r"--[^\n]*", " ", out)
    out = re.sub(r"'(?:''|[^'])*'", "''", out)
    out = re.sub(r'"(?:""|[^"])*"', '""', out)
    out = re.sub(r"`(?:``|[^`])*`", "``", out)
    out = re.sub(r"\s+", " ", out)
    return out.strip()


def classify_draft_sql_statement(sql: str) -> str:
    source = str(sql or "").strip()
    if source == "":
        raise ForgeError("sql is required", status_code=400)

    canonical = _canonicalize_sql(source)
    without_trailing = canonical[:-1].strip() if canonical.endswith(";") else canonical
    if ";" in without_trailing:
        raise ForgeError("Draft SQL must contain exactly one statement", status_code=400)

    upper = without_trailing.upper()
    if upper.startswith("SELECT ") or upper.startswith("WITH "):
        return "select"
    if re.match(r"^CREATE(\s+OR\s+REPLACE)?\s+VIEW\b", upper):
        forbidden = r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|TRUNCATE|CALL|EXECUTE|GRANT|REVOKE|OPTIMIZE|VACUUM|USE|COPY)\b"
        if re.search(forbidden, upper):
            raise ForgeError("Draft SQL may only execute SELECT or CREATE VIEW statements", status_code=400)
        if " AS " not in f" {upper} ":
            raise ForgeError("CREATE VIEW statement must include an AS clause", status_code=400)
        return "create_view"
    raise ForgeError("Draft SQL must start with SELECT, WITH, CREATE VIEW, or CREATE OR REPLACE VIEW", status_code=400)


def prepare_draft_execution_sql(
    sql: str,
    *,
    catalog_name: Optional[str],
    schema_name: Optional[str],
) -> str:
    statement_type = classify_draft_sql_statement(sql)
    if statement_type != "create_view" or (not catalog_name and not schema_name):
        return str(sql or "").strip()
    return _rewrite_create_view_target(
        str(sql or "").strip(),
        catalog_name=catalog_name,
        schema_name=schema_name,
    )


def parse_join_expr(expr: str) -> tuple[str, str, str]:
    pattern = r"^get_json_object\(\{(from|to)\}\.([A-Za-z0-9_]+),\s*'\$\.([A-Za-z0-9_]+)'\)$"
    match = re.match(pattern, expr)
    if not match:
        raise ForgeError(
            "Join spec expr must match get_json_object({from|to}.<col>, '$.<key>')",
            status_code=400,
        )
    return match.group(1), match.group(2), match.group(3)


def _rewrite_create_view_target(
    sql: str,
    *,
    catalog_name: Optional[str],
    schema_name: Optional[str],
) -> str:
    pattern = re.compile(
        r"^\s*(CREATE(?:\s+OR\s+REPLACE)?\s+VIEW)\s+(.+?)\s+(AS\b.*)$",
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = pattern.match(str(sql or "").strip())
    if not match:
        raise ForgeError("Unable to parse CREATE VIEW statement", status_code=400)
    prefix, target, suffix = match.groups()
    target_name = _extract_terminal_identifier(target)
    parts = [part for part in (catalog_name, schema_name, target_name) if part]
    rewritten_target = ".".join(_quote_identifier(part) for part in parts)
    return f"{prefix} {rewritten_target} {suffix}"


def _extract_terminal_identifier(target: str) -> str:
    raw = str(target or "").strip()
    if raw == "":
        raise ForgeError("CREATE VIEW target is required", status_code=400)
    pieces = [piece.strip() for piece in raw.split(".") if piece.strip()]
    if not pieces:
        raise ForgeError("CREATE VIEW target is invalid", status_code=400)
    terminal = pieces[-1].strip().strip("`").strip('"')
    return _require_sql_identifier(terminal, field="view_name")


__all__ = [
    "ForgeMatchViewDraftBuilder",
    "classify_draft_sql_statement",
    "normalize_optional_sql_identifier",
    "parse_join_expr",
    "prepare_draft_execution_sql",
]
