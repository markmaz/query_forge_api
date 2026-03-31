from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.services.domain.join.domain_join_repository import DomainJoinRepository
from app.services.domain.join.domain_join_validator import DomainJoinPayload, DomainJoinValidator


class DomainJoinCommandService:
    def __init__(self, *, repository: DomainJoinRepository, validator: DomainJoinValidator) -> None:
        self._repository = repository
        self._validator = validator

    def list_domain_joins(self, *, workspace_id: str, domain_id: int) -> List[Dict[str, Any]]:
        return self._repository.list_domain_joins(workspace_id=workspace_id, domain_id=domain_id)

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
        return self._validator.prepare_payload(
            domain_id=domain_id,
            from_workspace_table_id=from_workspace_table_id,
            to_workspace_table_id=to_workspace_table_id,
            join_type=join_type,
            join_spec=join_spec,
            sort_order=sort_order,
        )

    def create_join(self, *, workspace_id: str, payload: DomainJoinPayload) -> Dict[str, Any]:
        with self._repository.transaction() as tx:
            self._repository.ensure_domain(tx, workspace_id=workspace_id, domain_id=payload.domain_id)
            self._repository.ensure_tables_in_domain(
                tx,
                domain_id=payload.domain_id,
                qf_from_id=payload.from_workspace_table_id,
                qf_to_id=payload.to_workspace_table_id,
            )
            self._validator.validate_join_expr_columns(
                tx,
                payload.join_spec,
                qf_from_id=payload.from_workspace_table_id,
                qf_to_id=payload.to_workspace_table_id,
            )

            existing = self._repository.find_existing_join(tx, payload=payload)
            if existing:
                self._repository.reactivate_existing_join(tx, payload=payload, join_id=existing["id"])
                return {"ok": True, "id": str(existing["id"])}

            result = self._repository.insert_join(tx, payload=payload)
            join_id: Optional[Any]
            try:
                join_id = result.lastrowid
            except Exception:
                join_id = None
        return {"ok": True, "id": str(join_id) if join_id else None}

    def update_join(self, *, workspace_id: str, join_id: str, payload: DomainJoinPayload) -> Dict[str, Any]:
        with self._repository.transaction() as tx:
            self._repository.ensure_domain(tx, workspace_id=workspace_id, domain_id=payload.domain_id)
            self._repository.ensure_join_exists(tx, domain_id=payload.domain_id, join_id=join_id)
            self._repository.ensure_tables_in_domain(
                tx,
                domain_id=payload.domain_id,
                qf_from_id=payload.from_workspace_table_id,
                qf_to_id=payload.to_workspace_table_id,
            )
            self._validator.validate_join_expr_columns(
                tx,
                payload.join_spec,
                qf_from_id=payload.from_workspace_table_id,
                qf_to_id=payload.to_workspace_table_id,
            )
            self._repository.update_join(tx, payload=payload, join_id=join_id)
        return {"ok": True}

    def delete_join(self, *, workspace_id: str, domain_id: int, join_id: str) -> Dict[str, Any]:
        with self._repository.transaction() as tx:
            self._repository.ensure_domain(tx, workspace_id=workspace_id, domain_id=domain_id)
            self._repository.ensure_join_exists(tx, domain_id=domain_id, join_id=join_id)
            self._repository.deactivate_join(tx, domain_id=domain_id, join_id=join_id)
        return {"ok": True}

    def set_primary_table(self, *, workspace_id: str, domain_id: int, workspace_table_id: int) -> List[Dict[str, Any]]:
        with self._repository.transaction() as tx:
            self._repository.ensure_domain(tx, workspace_id=workspace_id, domain_id=domain_id)
            self._repository.ensure_primary_table_assigned(tx, domain_id=domain_id, workspace_table_id=workspace_table_id)
            self._repository.set_primary_flags(tx, domain_id=domain_id, workspace_table_id=workspace_table_id)
            return self._repository.list_domain_tables(tx, workspace_id=workspace_id, domain_id=domain_id)
