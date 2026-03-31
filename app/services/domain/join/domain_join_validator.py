from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol

from app.exceptions.forge_error import ForgeError

_JOIN_TYPES = frozenset({"LEFT", "INNER", "RIGHT"})


class QueryMappingsCapable(Protocol):
    def execute_query_mappings(self, query: str, params: Dict[str, Any] | None = None) -> list[Dict[str, Any]]:
        ...


@dataclass(frozen=True)
class DomainJoinPayload:
    domain_id: int
    from_workspace_table_id: int
    to_workspace_table_id: int
    join_type: str
    join_spec: Dict[str, Any]
    sort_order: int


class DomainJoinValidator:
    def __init__(self, *, expression_parser: Any) -> None:
        self._expression_parser = expression_parser

    def prepare_payload(
        self,
        *,
        domain_id: int,
        from_workspace_table_id: int,
        to_workspace_table_id: int,
        join_type: str,
        join_spec: Dict[str, Any],
        sort_order: int,
    ) -> DomainJoinPayload:
        self.validate_join_type(join_type)
        self.validate_join_spec(join_spec)

        from_id = int(from_workspace_table_id)
        to_id = int(to_workspace_table_id)
        if from_id == to_id:
            raise ForgeError("from_workspace_table_id must differ from to_workspace_table_id", status_code=400)

        self.validate_join_tables(join_spec, qf_from_id=from_id, qf_to_id=to_id)

        return DomainJoinPayload(
            domain_id=int(domain_id),
            from_workspace_table_id=from_id,
            to_workspace_table_id=to_id,
            join_type=join_type,
            join_spec=join_spec,
            sort_order=int(sort_order),
        )

    def validate_join_type(self, join_type: str) -> None:
        if join_type not in _JOIN_TYPES:
            raise ForgeError("Invalid join_type", status_code=400)

    def validate_join_spec(self, join_spec: Dict[str, Any]) -> None:
        if not isinstance(join_spec, dict):
            raise ForgeError("joinSpec must be an object", status_code=400)

        on_list = join_spec.get("on") or []
        if not isinstance(on_list, list) or not on_list:
            raise ForgeError("joinSpec.on must be a non-empty array", status_code=400)

        for item in on_list:
            if not isinstance(item, dict):
                raise ForgeError("joinSpec.on items must be objects", status_code=400)

            op = item.get("op")
            if op and op != "=":
                raise ForgeError("joinSpec.on only supports '=' operator", status_code=400)

            self.validate_join_side(item.get("left") or {}, qf_side_label="left")
            self.validate_join_side(item.get("right") or {}, qf_side_label="right")

    def validate_join_tables(self, join_spec: Dict[str, Any], *, qf_from_id: int, qf_to_id: int) -> None:
        for item in join_spec.get("on") or []:
            left = item.get("left") or {}
            right = item.get("right") or {}

            if left.get("workspaceTableId") is not None and int(left.get("workspaceTableId") or 0) != int(qf_from_id):
                raise ForgeError("joinSpec.left.workspaceTableId must match fromWorkspaceTableId", status_code=400)
            if right.get("workspaceTableId") is not None and int(right.get("workspaceTableId") or 0) != int(qf_to_id):
                raise ForgeError("joinSpec.right.workspaceTableId must match toWorkspaceTableId", status_code=400)

    def validate_join_side(self, side: Dict[str, Any], *, qf_side_label: str) -> None:
        if not isinstance(side, dict):
            raise ForgeError(f"joinSpec.{qf_side_label} must be an object", status_code=400)

        has_expr = bool(side.get("expr"))
        column_name = side.get("columnName") or side.get("col")
        has_column = bool(column_name)

        if has_expr and has_column:
            raise ForgeError(f"joinSpec.{qf_side_label} cannot include both expr and column", status_code=400)
        if not has_expr and not has_column:
            raise ForgeError(f"joinSpec.{qf_side_label} must include expr or column", status_code=400)

        if has_expr and not isinstance(side.get("expr"), str):
            raise ForgeError(f"joinSpec.{qf_side_label}.expr must be a string", status_code=400)
        if has_column and not isinstance(column_name, str):
            raise ForgeError(f"joinSpec.{qf_side_label}.column must be a string", status_code=400)

    def validate_join_expr_columns(
        self,
        tx: QueryMappingsCapable,
        join_spec: Dict[str, Any],
        *,
        qf_from_id: int,
        qf_to_id: int,
    ) -> None:
        for item in join_spec.get("on") or []:
            left = item.get("left") or {}
            right = item.get("right") or {}
            self.validate_expr_side(tx, left, expected_scope="from", workspace_table_id=qf_from_id, qf_side_label="left")
            self.validate_expr_side(tx, right, expected_scope="to", workspace_table_id=qf_to_id, qf_side_label="right")

    def validate_expr_side(
        self,
        tx: QueryMappingsCapable,
        side: Dict[str, Any],
        *,
        expected_scope: str,
        workspace_table_id: int,
        qf_side_label: str,
    ) -> None:
        expr = side.get("expr")
        if not expr:
            return

        scope, column_name, json_key = self._parse_json_expr(expr)
        if scope != expected_scope:
            raise ForgeError(
                f"joinSpec.{qf_side_label}.expr must reference {{{expected_scope}}} columns",
                status_code=400,
            )
        if not self.column_exists(tx, workspace_table_id, column_name):
            raise ForgeError(
                f"joinSpec.{qf_side_label}.expr column '{column_name}' not found on workspace table {workspace_table_id}",
                status_code=400,
            )
        if not json_key:
            raise ForgeError(f"joinSpec.{qf_side_label}.expr must include a JSON key", status_code=400)

    def column_exists(self, tx: QueryMappingsCapable, workspace_table_id: int, column_name: str) -> bool:
        rows = tx.execute_query_mappings(
            """
            SELECT 1
            FROM workspace_column
            WHERE workspace_table_id = :wtid
              AND column_name = :col
            LIMIT 1
            """,
            {"wtid": int(workspace_table_id), "col": column_name},
        )
        return bool(rows)

    def _parse_json_expr(self, expr: str):
        parser = self._expression_parser
        if hasattr(parser, "parse_json_expr"):
            return parser.parse_json_expr(expr)
        if hasattr(parser, "_parse_json_expr"):
            return parser._parse_json_expr(expr)
        raise AttributeError("Expression parser must define parse_json_expr or _parse_json_expr")
