from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor
from app.services.shared.jsonify import jsonify_dict


class DomainTableWriteService:
    """
    Domain ⇄ workspace_table mapping (domain_workspace_table).

    Permission: requires can_edit=1 on the domain.

    Supports:
      - add_table(...) / remove_table(...) (single)
      - apply_changes(..., add=[...], remove=[...]) (batch)  ✅ matches FE payload
    """

    def __init__(self, *, sql: Optional[SQLExecutor] = None) -> None:
        self._sql = sql or MySQLSQLExecutor()

    # ---------- permission ----------

    def _assert_can_edit_domain(self, *, workspace_id: str, user_id: str, domain_id: int) -> None:
        sql = """
SELECT 1
FROM user_domain_mapping udm
JOIN domain d ON d.id = udm.domain_id
WHERE d.workspace_id=:ws
  AND d.id=:did
  AND d.is_active=1
  AND udm.user_id=:uid
  AND udm.can_edit=1
LIMIT 1
"""
        row = self._sql.execute_query(sql, {"ws": workspace_id, "did": int(domain_id), "uid": user_id})
        if not row:
            raise ServiceError("You do not have edit permission for this domain.", status_code=403)

    # ---------- helpers ----------

    @staticmethod
    def _normalize_ids(vals: Optional[Iterable[Any]], field: str) -> List[int]:
        if vals is None:
            return []
        if not isinstance(vals, (list, tuple)):
            raise ServiceError(f"'{field}' must be a list of integers", status_code=400)

        out: List[int] = []
        for v in vals:
            try:
                iv = int(v)
            except Exception:
                raise ServiceError(f"'{field}' must contain integers", status_code=400)
            if iv <= 0:
                raise ServiceError(f"'{field}' must contain positive integers", status_code=400)
            out.append(iv)

        # dedupe preserve order
        seen = set()
        deduped: List[int] = []
        for iv in out:
            if iv in seen:
                continue
            seen.add(iv)
            deduped.append(iv)
        return deduped

    # ---------- single-item CRUD (keep) ----------

    def add_table(
        self,
        *,
        workspace_id: str,
        user_id: str,
        domain_id: int,
        workspace_table_id: int,
    ) -> Dict[str, Any]:
        self._assert_can_edit_domain(workspace_id=workspace_id, user_id=user_id, domain_id=domain_id)

        sql_validate = """
SELECT
  (SELECT 1 FROM domain WHERE workspace_id=:ws AND id=:did LIMIT 1) AS ok_domain,
  (SELECT 1 FROM workspace_table WHERE workspace_id=:ws AND id=:wtid LIMIT 1) AS ok_table
"""
        with self._sql.transaction() as tx:
            v_rows = tx.execute_query_mappings(
                sql_validate,
                {"ws": workspace_id, "did": int(domain_id), "wtid": int(workspace_table_id)},
            )
            v = v_rows[0] if v_rows else None

            if not v or int(v.get("ok_domain") or 0) != 1:
                raise ServiceError("Domain not found", status_code=404)
            if int(v.get("ok_table") or 0) != 1:
                raise ServiceError("Workspace table not found", status_code=404)

            tx.execute_write(
                """
INSERT INTO domain_workspace_table (domain_id, workspace_table_id, created_at)
VALUES (:did, :wtid, CURRENT_TIMESTAMP)
ON DUPLICATE KEY UPDATE created_at=created_at
""",
                {"did": int(domain_id), "wtid": int(workspace_table_id)},
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
    ) -> Dict[str, Any]:
        self._assert_can_edit_domain(workspace_id=workspace_id, user_id=user_id, domain_id=domain_id)

        relation_kind_val = (relation_kind or "JOIN").upper()
        if relation_kind_val not in {"JOIN", "UNION"}:
            raise ServiceError("relationKind must be JOIN or UNION", status_code=400)

        filter_mode_val = (filter_mode or "AUTO").upper() if filter_mode_set else None
        if filter_mode_val and filter_mode_val not in {"AUTO", "WHERE", "EXISTS"}:
            raise ServiceError("filterMode must be AUTO, WHERE, or EXISTS", status_code=400)

        cardinality_val = (cardinality or "ONE").upper() if cardinality_set else None
        if cardinality_val and cardinality_val not in {"ONE", "MANY"}:
            raise ServiceError("cardinality must be ONE or MANY", status_code=400)

        sql_validate = """
SELECT
  (SELECT 1 FROM domain WHERE workspace_id=:ws AND id=:did LIMIT 1) AS ok_domain,
  (SELECT 1 FROM workspace_table WHERE workspace_id=:ws AND id=:wtid LIMIT 1) AS ok_table
"""
        with self._sql.transaction() as tx:
            v_rows = tx.execute_query_mappings(
                sql_validate,
                {"ws": workspace_id, "did": int(domain_id), "wtid": int(workspace_table_id)},
            )
            v = v_rows[0] if v_rows else None

            if not v or int(v.get("ok_domain") or 0) != 1:
                raise ServiceError("Domain not found", status_code=404)
            if int(v.get("ok_table") or 0) != 1:
                raise ServiceError("Workspace table not found", status_code=404)

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
                    "relation_kind": relation_kind_val,
                    "sort_order": int(sort_order) if sort_order is not None else 0,
                    "role": role,
                    "table_alias": table_alias,
                    "filter_mode": filter_mode_val or "AUTO",
                    "cardinality": cardinality_val or "ONE",
                },
            )

            updates = []
            params: Dict[str, Any] = {"did": int(domain_id), "wtid": int(workspace_table_id)}
            if relation_kind_set:
                updates.append("relation_kind = :relation_kind")
                params["relation_kind"] = relation_kind_val
            if role_set:
                updates.append("role = :role")
                params["role"] = role
            if sort_order_set:
                updates.append("sort_order = :sort_order")
                params["sort_order"] = int(sort_order)
            if table_alias_set:
                updates.append("table_alias = :table_alias")
                params["table_alias"] = table_alias
            if filter_mode_set:
                updates.append("filter_mode = :filter_mode")
                params["filter_mode"] = filter_mode_val or "AUTO"
            if cardinality_set:
                updates.append("cardinality = :cardinality")
                params["cardinality"] = cardinality_val or "ONE"

            if updates:
                tx.execute_write(
                    f"""
UPDATE domain_workspace_table
SET {", ".join(updates)}
WHERE domain_id = :did
  AND workspace_table_id = :wtid
""",
                    params,
                )

            if set_primary_if_empty:
                has_primary = tx.execute_query(
                    "SELECT 1 FROM domain_workspace_table WHERE domain_id = :did AND is_primary = 1 LIMIT 1",
                    {"did": int(domain_id)},
                )
                if not has_primary:
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

            sql_row = """
                SELECT
                wt.id               AS workspace_table_id,
                d.model_table_id    AS model_table_id,
                mt.name             AS model_table_name,
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
                JOIN domain d
                ON d.id = dwt.domain_id
                JOIN workspace_table wt
                ON wt.id = dwt.workspace_table_id
                LEFT JOIN model_table mt
                ON mt.id = d.model_table_id
                WHERE d.workspace_id = :ws
                AND d.id = :did
                AND dwt.workspace_table_id = :wtid
                LIMIT 1;
            """
            row_rows = tx.execute_query_mappings(
                sql_row, {"ws": workspace_id, "did": int(domain_id), "wtid": int(workspace_table_id)}
            )
            row = row_rows[0] if row_rows else None

        return jsonify_dict(dict(row)) if row else {}

    def remove_table(
        self,
        *,
        workspace_id: str,
        user_id: str,
        domain_id: int,
        workspace_table_id: int,
    ) -> Dict[str, Any]:
        self._assert_can_edit_domain(workspace_id=workspace_id, user_id=user_id, domain_id=domain_id)

        with self._sql.transaction() as tx:
            ok = tx.execute_query(
                "SELECT 1 FROM domain WHERE workspace_id=:ws AND id=:did LIMIT 1",
                {"ws": workspace_id, "did": int(domain_id)},
            )
            if not ok:
                raise ServiceError("Domain not found", status_code=404)

            res = tx.execute_write(
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

        return {"ok": True, "deleted": int(res or 0)}

    # ---------- batch apply (new) ----------

    def apply_changes(
        self,
        *,
        workspace_id: str,
        user_id: str,
        domain_id: int,
        add: Optional[Iterable[Any]] = None,
        remove: Optional[Iterable[Any]] = None,
    ) -> Dict[str, Any]:
        """
        Apply batch changes from the frontend:
          { add: number[], remove: number[] }

        Returns:
          { ok: true, added: <n>, removed: <n> }
        """
        self._assert_can_edit_domain(workspace_id=workspace_id, user_id=user_id, domain_id=domain_id)

        add_ids = self._normalize_ids(add, "add")
        remove_ids = self._normalize_ids(remove, "remove")

        if not add_ids and not remove_ids:
            return {"ok": True, "added": 0, "removed": 0}

        # Validate domain and all table ids in ONE shot (faster than per-row)
        check_ids = sorted(set(add_ids + remove_ids))

        with self._sql.transaction() as tx:
            ok_domain = tx.execute_query(
                "SELECT 1 FROM domain WHERE workspace_id=:ws AND id=:did LIMIT 1",
                {"ws": workspace_id, "did": int(domain_id)},
            )
            if not ok_domain:
                raise ServiceError("Domain not found", status_code=404)

            if check_ids:
                placeholders = ",".join([f":id{i}" for i in range(len(check_ids))])
                params: Dict[str, Any] = {"ws": workspace_id}
                params.update({f"id{i}": v for i, v in enumerate(check_ids)})

                found = tx.execute_query_mappings(
                    f"""
SELECT id
FROM workspace_table
WHERE workspace_id=:ws AND id IN ({placeholders})
""",
                    params,
                )

                found_ids = {int(r["id"]) for r in found}
                missing = [v for v in check_ids if v not in found_ids]
                if missing:
                    raise ServiceError(f"Workspace table not found: {missing}", status_code=404)

            removed_ct = 0
            added_ct = 0

            # Remove in one statement
            if remove_ids:
                placeholders = ",".join([f":rid{i}" for i in range(len(remove_ids))])
                params = {"ws": workspace_id, "did": int(domain_id)}
                params.update({f"rid{i}": v for i, v in enumerate(remove_ids)})

                res = tx.execute_write(
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
                removed_ct = int(res or 0)

            # Add in a loop using your ON DUPLICATE KEY behavior
            if add_ids:
                for wt_id in add_ids:
                    tx.execute_write(
                        """
INSERT INTO domain_workspace_table (domain_id, workspace_table_id, created_at)
VALUES (:did, :wtid, CURRENT_TIMESTAMP)
ON DUPLICATE KEY UPDATE created_at=created_at
""",
                        {"did": int(domain_id), "wtid": int(wt_id)},
                    )
                # this is "requested adds", not "newly inserted" (fine for UI)
                added_ct = len(add_ids)

        return {"ok": True, "added": added_ct, "removed": removed_ct}
