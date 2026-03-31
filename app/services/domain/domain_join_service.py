from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort, ForgeQueryTx
from app.services.domain.join import (
    DomainJoinCommandService,
    DomainJoinExpressionParser,
    DomainJoinRepository,
    DomainJoinValidator,
)


class DomainJoinService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._expression_parser = DomainJoinExpressionParser()
        self._validator = DomainJoinValidator(expression_parser=self)
        self._repository = DomainJoinRepository(sql=self._sql)
        self._commands = DomainJoinCommandService(repository=self._repository, validator=self._validator)

    def list_domain_joins(self, *, workspace_id: str, domain_id: int) -> List[Dict[str, Any]]:
        return self._commands.list_domain_joins(workspace_id=workspace_id, domain_id=domain_id)

    def create_join(
        self,
        *,
        workspace_id: str,
        domain_id: int,
        from_workspace_table_id: int,
        to_workspace_table_id: int,
        join_type: str,
        join_spec: Dict[str, Any],
        sort_order: int = 0,
    ) -> Dict[str, Any]:
        payload = self._prepare_payload(
            domain_id=domain_id,
            from_workspace_table_id=from_workspace_table_id,
            to_workspace_table_id=to_workspace_table_id,
            join_type=join_type,
            join_spec=join_spec,
            sort_order=sort_order,
        )
        return self._commands.create_join(workspace_id=workspace_id, payload=payload)

    def update_join(
        self,
        *,
        workspace_id: str,
        domain_id: int,
        join_id: str,
        from_workspace_table_id: int,
        to_workspace_table_id: int,
        join_type: str,
        join_spec: Dict[str, Any],
        sort_order: int = 0,
    ) -> Dict[str, Any]:
        payload = self._prepare_payload(
            domain_id=domain_id,
            from_workspace_table_id=from_workspace_table_id,
            to_workspace_table_id=to_workspace_table_id,
            join_type=join_type,
            join_spec=join_spec,
            sort_order=sort_order,
        )
        return self._commands.update_join(workspace_id=workspace_id, join_id=join_id, payload=payload)

    def delete_join(self, *, workspace_id: str, domain_id: int, join_id: str) -> Dict[str, Any]:
        return self._commands.delete_join(workspace_id=workspace_id, domain_id=domain_id, join_id=join_id)

    def set_primary_table(self, *, workspace_id: str, domain_id: int, workspace_table_id: int) -> List[Dict[str, Any]]:
        return self._commands.set_primary_table(
            workspace_id=workspace_id,
            domain_id=domain_id,
            workspace_table_id=workspace_table_id,
        )

    def _prepare_payload(
        self,
        *,
        domain_id: int,
        from_workspace_table_id: int,
        to_workspace_table_id: int,
        join_type: str,
        join_spec: Dict[str, Any],
        sort_order: int,
    ):
        return self._commands.prepare_payload(
            domain_id=domain_id,
            from_workspace_table_id=from_workspace_table_id,
            to_workspace_table_id=to_workspace_table_id,
            join_type=join_type,
            join_spec=join_spec,
            sort_order=sort_order,
        )

    def _ensure_domain(self, tx: ForgeQueryTx, workspace_id: str, domain_id: int) -> None:
        self._repository.ensure_domain(tx, workspace_id=workspace_id, domain_id=domain_id)

    def _ensure_tables_in_domain(self, tx: ForgeQueryTx, domain_id: int, qf_from_id: int, qf_to_id: int) -> None:
        self._repository.ensure_tables_in_domain(
            tx,
            domain_id=domain_id,
            qf_from_id=qf_from_id,
            qf_to_id=qf_to_id,
        )

    def _ensure_join_exists(self, tx: ForgeQueryTx, domain_id: int, join_id: str) -> None:
        self._repository.ensure_join_exists(tx, domain_id=domain_id, join_id=join_id)

    def _validate_join_type(self, join_type: str) -> None:
        self._validator.validate_join_type(join_type)

    def _validate_join_spec(self, join_spec: Dict[str, Any]) -> None:
        self._validator.validate_join_spec(join_spec)

    def _validate_join_tables(self, join_spec: Dict[str, Any], qf_from_id: int, qf_to_id: int) -> None:
        self._validator.validate_join_tables(join_spec, qf_from_id=qf_from_id, qf_to_id=qf_to_id)

    def _validate_join_side(self, side: Dict[str, Any], *, qf_side_label: str) -> None:
        self._validator.validate_join_side(side, qf_side_label=qf_side_label)

    def _validate_join_expr_columns(self, tx: ForgeQueryTx, join_spec: Dict[str, Any], qf_from_id: int, qf_to_id: int) -> None:
        self._validator.validate_join_expr_columns(
            tx,
            join_spec,
            qf_from_id=qf_from_id,
            qf_to_id=qf_to_id,
        )

    def _validate_expr_side(
        self,
        tx,
        side: Dict[str, Any],
        *,
        expected_scope: str,
        workspace_table_id: int,
        qf_side_label: str,
    ) -> None:
        self._validator.validate_expr_side(
            tx,
            side,
            expected_scope=expected_scope,
            workspace_table_id=workspace_table_id,
            qf_side_label=qf_side_label,
        )

    def _parse_json_expr(self, expr: str) -> Tuple[str, str, str]:
        return self._expression_parser.parse_json_expr(expr)

    def _column_exists(self, tx, workspace_table_id: int, column_name: str) -> bool:
        return self._validator.column_exists(tx, workspace_table_id, column_name)
