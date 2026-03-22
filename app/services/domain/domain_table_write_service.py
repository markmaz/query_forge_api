from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.shared.jsonify import serialize_record

_ALLOWED_RELATION_KINDS = frozenset({"JOIN", "UNION"})
_ALLOWED_FILTER_MODES = frozenset({"AUTO", "WHERE", "EXISTS"})
_ALLOWED_CARDINALITY = frozenset({"ONE", "MANY"})


@dataclass(frozen=True)
class _DomainTableContext:
    workspace_id: str
    user_id: str
    domain_id: int


@dataclass(frozen=True)
class _DomainTableMutation:
    relation_kind: str
    sort_order: int
    role: Optional[str]
    table_alias: Optional[str]
    filter_mode: str
    cardinality: str


class _DomainTableStore:
    def __init__(self, *, sql: ForgeQueryPort) -> None:
        self._sql = sql

    def user_can_edit_domain(self, *, ctx: _DomainTableContext) -> bool:
        rows = self._sql.execute_query(
            """
            SELECT 1
            FROM user_domain_mapping udm
            JOIN domain d ON d.id = udm.domain_id
            WHERE d.workspace_id=:ws
              AND d.id=:did
              AND d.is_active=1
              AND udm.user_id=:uid
              AND udm.can_edit=1
            LIMIT 1
            """,
            {"ws": ctx.workspace_id, "did": ctx.domain_id, "uid": ctx.user_id},
        )
        return bool(rows)

    def validate_domain_and_table(self, *, ctx: _DomainTableContext, workspace_table_id: int) -> Dict[str, Any]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              (SELECT 1 FROM domain WHERE workspace_id=:ws AND id=:did LIMIT 1) AS ok_domain,
              (SELECT 1 FROM workspace_table WHERE workspace_id=:ws AND id=:wtid LIMIT 1) AS ok_table
            """,
            {"ws": ctx.workspace_id, "did": ctx.domain_id, "wtid": int(workspace_table_id)},
        )
        return dict(rows[0]) if rows else {}

    def domain_exists(self, *, workspace_id: str, domain_id: int) -> bool:
        rows = self._sql.execute_query(
            "SELECT 1 FROM domain WHERE workspace_id=:ws AND id=:did LIMIT 1",
            {"ws": workspace_id, "did": int(domain_id)},
        )
        return bool(rows)

    def upsert_domain_table(self, *, domain_id: int, workspace_table_id: int, mutation: _DomainTableMutation) -> None:
        with self._sql.transaction() as tx:
            tx.execute_write(
                """
                INSERT INTO domain_workspace_table
                  (domain_id, workspace_table_id, relation_kind, is_primary, sort_order, role, table_alias, filter_mode, cardinality, created_at)
                VALUES
                  (:did, :wtid, :relation_kind, 0, :sort_order, :role, :table_alias, :filter_mode, :cardinality, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE workspace_table_id=workspace_table_id
                """,
                {
                    "did": int(domain_id),
                    "wtid": int(workspace_table_id),
                    "relation_kind": mutation.relation_kind,
                    "sort_order": int(mutation.sort_order),
                    "role": mutation.role,
                    "table_alias": mutation.table_alias,
                    "filter_mode": mutation.filter_mode,
                    "cardinality": mutation.cardinality,
                },
            )

    def update_domain_table_fields(self, *, domain_id: int, workspace_table_id: int, updates: Dict[str, Any]) -> None:
        if not updates:
            return
        set_clauses = [f"{field} = :{field}" for field in updates]
        params = {"did": int(domain_id), "wtid": int(workspace_table_id), **updates}
        with self._sql.transaction() as tx:
            tx.execute_write(
                f"""
                UPDATE domain_workspace_table
                SET {", ".join(set_clauses)}
                WHERE domain_id = :did
                  AND workspace_table_id = :wtid
                """,
                params,
            )

    def domain_has_primary(self, *, domain_id: int) -> bool:
        rows = self._sql.execute_query(
            "SELECT 1 FROM domain_workspace_table WHERE domain_id = :did AND is_primary = 1 LIMIT 1",
            {"did": int(domain_id)},
        )
        return bool(rows)

    def set_primary_table(self, *, domain_id: int, workspace_table_id: int) -> None:
        with self._sql.transaction() as tx:
            tx.execute_write(
                "UPDATE domain_workspace_table SET is_primary = 0 WHERE domain_id = :did",
                {"did": int(domain_id)},
            )
            tx.execute_write(
                """
                UPDATE domain_workspace_table
                SET is_primary = 1
                WHERE domain_id = :did
                  AND workspace_table_id = :wtid
                """,
                {"did": int(domain_id), "wtid": int(workspace_table_id)},
            )

    def fetch_domain_table_row(self, *, workspace_id: str, domain_id: int, workspace_table_id: int) -> Optional[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              wt.id               AS workspace_table_id,
              COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name) AS table_label,
              dwt.relation_kind   AS relation_kind,
              dwt.is_primary      AS is_primary,
              dwt.sort_order      AS sort_order,
              dwt.table_alias     AS table_alias,
              dwt.role            AS role,
              wt.catalog_name,
              wt.schema_name,
              wt.table_name,
              wt.full_name,
              wt.variant_code,
              wt.is_qe,
              wt.exists_in_dbx,
              wt.last_seen_at
            FROM domain_workspace_table dwt
            JOIN domain d ON d.id = dwt.domain_id
            JOIN workspace_table wt ON wt.id = dwt.workspace_table_id
            WHERE d.workspace_id = :ws
              AND d.id = :did
              AND dwt.workspace_table_id = :wtid
            LIMIT 1
            """,
            {"ws": workspace_id, "did": int(domain_id), "wtid": int(workspace_table_id)},
        )
        if not rows:
            return None
        row = dict(rows[0])
        row["model_table_id"] = row.get("workspace_table_id")
        row["model_table_name"] = row.get("table_label")
        return row

    def remove_domain_table(self, *, workspace_id: str, domain_id: int, workspace_table_id: int) -> int:
        with self._sql.transaction() as tx:
            return tx.execute_write(
                """
                DELETE dwt
                FROM domain_workspace_table dwt
                JOIN domain d ON d.id = dwt.domain_id
                WHERE d.workspace_id=:ws
                  AND dwt.domain_id=:did
                  AND dwt.workspace_table_id=:wtid
                """,
                {"ws": workspace_id, "did": int(domain_id), "wtid": int(workspace_table_id)},
            )


class DomainTableWriteService:
    """Domain <-> workspace_table mapping writes."""

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._store = _DomainTableStore(sql=self._sql)

    def _assert_can_edit_domain(self, *, workspace_id: str, user_id: str, domain_id: int) -> None:
        ctx = _DomainTableContext(workspace_id=workspace_id, user_id=user_id, domain_id=int(domain_id))
        if not self._store.user_can_edit_domain(ctx=ctx):
            raise ForgeError("You do not have edit permission for this domain.", status_code=403)

    @staticmethod
    def _normalize_ids(vals: Optional[Iterable[Any]], field: str) -> List[int]:
        if vals is None:
            return []
        if not isinstance(vals, (list, tuple)):
            raise ForgeError(f"'{field}' must be a list of integers", status_code=400)

        out: List[int] = []
        for value in vals:
            try:
                parsed = int(value)
            except Exception:
                raise ForgeError(f"'{field}' must contain integers", status_code=400)
            if parsed <= 0:
                raise ForgeError(f"'{field}' must contain positive integers", status_code=400)
            out.append(parsed)

        seen = set()
        deduped: List[int] = []
        for value in out:
            if value in seen:
                continue
            seen.add(value)
            deduped.append(value)
        return deduped

    @staticmethod
    def _normalize_relation_kind(value: Optional[str]) -> str:
        relation = (value or "JOIN").upper()
        if relation not in _ALLOWED_RELATION_KINDS:
            raise ForgeError("relationKind must be JOIN or UNION", status_code=400)
        return relation

    @staticmethod
    def _normalize_filter_mode(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        mode = (value or "AUTO").upper()
        if mode not in _ALLOWED_FILTER_MODES:
            raise ForgeError("filterMode must be AUTO, WHERE, or EXISTS", status_code=400)
        return mode

    @staticmethod
    def _normalize_cardinality(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cardinality = (value or "ONE").upper()
        if cardinality not in _ALLOWED_CARDINALITY:
            raise ForgeError("cardinality must be ONE or MANY", status_code=400)
        return cardinality

    def _validate_domain_and_table_or_raise(self, *, ctx: _DomainTableContext, workspace_table_id: int) -> None:
        validation = self._store.validate_domain_and_table(ctx=ctx, workspace_table_id=int(workspace_table_id))
        if int(validation.get("ok_domain") or 0) != 1:
            raise ForgeError("Domain not found", status_code=404)
        if int(validation.get("ok_table") or 0) != 1:
            raise ForgeError("Workspace table not found", status_code=404)

    def add_table(
        self,
        *,
        workspace_id: str,
        user_id: str,
        domain_id: int,
        workspace_table_id: int,
    ) -> Dict[str, Any]:
        self._assert_can_edit_domain(workspace_id=workspace_id, user_id=user_id, domain_id=domain_id)
        ctx = _DomainTableContext(workspace_id=workspace_id, user_id=user_id, domain_id=int(domain_id))
        self._validate_domain_and_table_or_raise(ctx=ctx, workspace_table_id=int(workspace_table_id))

        self._store.upsert_domain_table(
            domain_id=int(domain_id),
            workspace_table_id=int(workspace_table_id),
            mutation=_DomainTableMutation(
                relation_kind="JOIN",
                sort_order=0,
                role=None,
                table_alias=None,
                filter_mode="AUTO",
                cardinality="ONE",
            ),
        )

        return {"ok": True, "domain_id": int(domain_id), "workspace_table_id": int(workspace_table_id)}

    def add_or_update_table(
        self,
        *,
        workspace_id: str,
        user_id: str,
        domain_id: int,
        workspace_table_id: int,
        relation_kind: Optional[str] = None,
        relation_kind_set: bool = False,
        role: Optional[str] = None,
        role_set: bool = False,
        sort_order: Optional[int] = None,
        sort_order_set: bool = False,
        table_alias: Optional[str] = None,
        table_alias_set: bool = False,
        filter_mode: Optional[str] = None,
        filter_mode_set: bool = False,
        cardinality: Optional[str] = None,
        cardinality_set: bool = False,
        set_primary_if_empty: bool = True,
        bypass_permissions: bool = False,
    ) -> Dict[str, Any]:
        if not bypass_permissions:
            self._assert_can_edit_domain(workspace_id=workspace_id, user_id=user_id, domain_id=domain_id)

        relation_kind_val = self._normalize_relation_kind(relation_kind)
        filter_mode_val = self._normalize_filter_mode(filter_mode)
        cardinality_val = self._normalize_cardinality(cardinality)

        ctx = _DomainTableContext(workspace_id=workspace_id, user_id=user_id, domain_id=int(domain_id))
        self._validate_domain_and_table_or_raise(ctx=ctx, workspace_table_id=int(workspace_table_id))

        mutation = _DomainTableMutation(
            relation_kind=relation_kind_val,
            sort_order=int(sort_order) if sort_order is not None else 0,
            role=role,
            table_alias=table_alias,
            filter_mode=filter_mode_val or "AUTO",
            cardinality=cardinality_val or "ONE",
        )
        self._store.upsert_domain_table(
            domain_id=int(domain_id),
            workspace_table_id=int(workspace_table_id),
            mutation=mutation,
        )

        updates: Dict[str, Any] = {}
        if relation_kind_set:
            updates["relation_kind"] = relation_kind_val
        if role_set:
            updates["role"] = role
        if sort_order_set:
            updates["sort_order"] = int(sort_order)
        if table_alias_set:
            updates["table_alias"] = table_alias
        if filter_mode_set:
            updates["filter_mode"] = filter_mode_val or "AUTO"
        if cardinality_set:
            updates["cardinality"] = cardinality_val or "ONE"
        self._store.update_domain_table_fields(
            domain_id=int(domain_id),
            workspace_table_id=int(workspace_table_id),
            updates=updates,
        )

        if set_primary_if_empty and not self._store.domain_has_primary(domain_id=int(domain_id)):
            self._store.set_primary_table(domain_id=int(domain_id), workspace_table_id=int(workspace_table_id))

        row = self._store.fetch_domain_table_row(
            workspace_id=workspace_id,
            domain_id=int(domain_id),
            workspace_table_id=int(workspace_table_id),
        )
        return serialize_record(row) if row else {}

    def remove_table(
        self,
        *,
        workspace_id: str,
        user_id: str,
        domain_id: int,
        workspace_table_id: int,
    ) -> Dict[str, Any]:
        self._assert_can_edit_domain(workspace_id=workspace_id, user_id=user_id, domain_id=domain_id)

        if not self._store.domain_exists(workspace_id=workspace_id, domain_id=int(domain_id)):
            raise ForgeError("Domain not found", status_code=404)

        deleted = self._store.remove_domain_table(
            workspace_id=workspace_id,
            domain_id=int(domain_id),
            workspace_table_id=int(workspace_table_id),
        )
        return {"ok": True, "deleted": int(deleted or 0)}

    def apply_changes(
        self,
        *,
        workspace_id: str,
        user_id: str,
        domain_id: int,
        add: Optional[Iterable[Any]] = None,
        remove: Optional[Iterable[Any]] = None,
        bypass_permissions: bool = False,
    ) -> Dict[str, Any]:
        if not bypass_permissions:
            self._assert_can_edit_domain(workspace_id=workspace_id, user_id=user_id, domain_id=domain_id)

        add_ids = self._normalize_ids(add, "add")
        remove_ids = self._normalize_ids(remove, "remove")

        if not add_ids and not remove_ids:
            return {"ok": True, "added": 0, "removed": 0}

        check_ids = sorted(set(add_ids + remove_ids))

        with self._sql.transaction() as tx:
            ok_domain = tx.execute_query(
                "SELECT 1 FROM domain WHERE workspace_id=:ws AND id=:did LIMIT 1",
                {"ws": workspace_id, "did": int(domain_id)},
            )
            if not ok_domain:
                raise ForgeError("Domain not found", status_code=404)

            if check_ids:
                placeholders = ",".join(f":id{i}" for i in range(len(check_ids)))
                params: Dict[str, Any] = {"ws": workspace_id, **{f"id{i}": value for i, value in enumerate(check_ids)}}
                found = tx.execute_query_mappings(
                    f"""
                    SELECT id
                    FROM workspace_table
                    WHERE workspace_id=:ws AND id IN ({placeholders})
                    """,
                    params,
                )
                found_ids = {int(row["id"]) for row in found}
                missing = [value for value in check_ids if value not in found_ids]
                if missing:
                    raise ForgeError(f"Workspace table not found: {missing}", status_code=404)

            removed_count = 0
            if remove_ids:
                placeholders = ",".join(f":rid{i}" for i in range(len(remove_ids)))
                params = {
                    "ws": workspace_id,
                    "did": int(domain_id),
                    **{f"rid{i}": value for i, value in enumerate(remove_ids)},
                }
                removed_count = int(
                    tx.execute_write(
                        f"""
                        DELETE dwt
                        FROM domain_workspace_table dwt
                        JOIN domain d ON d.id = dwt.domain_id
                        WHERE d.workspace_id=:ws
                          AND dwt.domain_id=:did
                          AND dwt.workspace_table_id IN ({placeholders})
                        """,
                        params,
                    )
                    or 0
                )

            for workspace_table_id in add_ids:
                tx.execute_write(
                    """
                    INSERT INTO domain_workspace_table (domain_id, workspace_table_id, created_at)
                    VALUES (:did, :wtid, CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE created_at=created_at
                    """,
                    {"did": int(domain_id), "wtid": int(workspace_table_id)},
                )

        return {"ok": True, "added": len(add_ids), "removed": removed_count}
