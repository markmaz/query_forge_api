from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.adapters.mysql_sql_executor import MySQLSQLExecutor
from app.exceptions.service_error import ServiceError
from app.ports.sql_executor import SQLExecutor


class DomainUserWriteService:
    """
    Domain ⇄ users mapping (user_domain_mapping)

    Permission: requires can_edit=1 on the domain.

    Supports:
      - upsert_user(...) / remove_user(...) (single)
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
    def _norm_user_id(v: Any) -> str:
        s = (str(v) if v is not None else "").strip()
        if not s:
            raise ServiceError("user_id is required", status_code=400)
        return s

    @staticmethod
    def _norm_remove(vals: Optional[Iterable[Any]]) -> List[str]:
        if vals is None:
            return []
        if not isinstance(vals, (list, tuple)):
            raise ServiceError("'remove' must be a list of user_id strings", status_code=400)

        out: List[str] = []
        for v in vals:
            out.append(DomainUserWriteService._norm_user_id(v))

        # dedupe preserve order
        seen = set()
        deduped: List[str] = []
        for s in out:
            if s in seen:
                continue
            seen.add(s)
            deduped.append(s)
        return deduped

    @staticmethod
    def _norm_add(vals: Optional[Iterable[Any]]) -> List[Tuple[str, bool]]:
        """
        Accepts: [{ user_id, can_edit? }, ...]
        Returns: [(user_id, can_edit_bool), ...]
        """
        if vals is None:
            return []
        if not isinstance(vals, (list, tuple)):
            raise ServiceError("'add' must be a list of objects", status_code=400)

        out: List[Tuple[str, bool]] = []
        for item in vals:
            if not isinstance(item, dict):
                raise ServiceError("'add' must contain objects like {user_id, can_edit?}", status_code=400)

            uid = DomainUserWriteService._norm_user_id(item.get("user_id"))
            can_edit = item.get("can_edit", False)

            # normalize bool-ish
            if isinstance(can_edit, (int, str)):
                s = str(can_edit).strip().lower()
                if s in ("1", "true", "yes", "y", "on"):
                    can_edit_b = True
                elif s in ("0", "false", "no", "n", "off", ""):
                    can_edit_b = False
                else:
                    raise ServiceError("'can_edit' must be boolean", status_code=400)
            elif isinstance(can_edit, bool):
                can_edit_b = can_edit
            else:
                raise ServiceError("'can_edit' must be boolean", status_code=400)

            out.append((uid, can_edit_b))

        # dedupe by user_id (keep last occurrence)
        m: Dict[str, bool] = {}
        order: List[str] = []
        for uid, ce in out:
            if uid not in m:
                order.append(uid)
            m[uid] = ce
        return [(uid, m[uid]) for uid in order]

    # ---------- single-item CRUD (keep) ----------

    def upsert_user(
        self,
        *,
        workspace_id: str,
        editor_user_id: str,
        domain_id: int,
        target_user_id: str,
        can_read: bool = True,
        can_edit: bool = False,
    ) -> Dict[str, Any]:
        self._assert_can_edit_domain(workspace_id=workspace_id, user_id=editor_user_id, domain_id=domain_id)

        target_user_id = self._norm_user_id(target_user_id)

        # Validate domain belongs to workspace AND user belongs to workspace
        sql_validate = """
                SELECT
                (SELECT 1 FROM domain WHERE workspace_id=:ws AND id=:did AND is_active=1 LIMIT 1) AS ok_domain,
                (SELECT 1
                    FROM user_workspace_map uwm
                    JOIN users u ON u.user_id = uwm.user_id
                    WHERE uwm.workspace_id=:ws AND uwm.user_id=:tuid
                    LIMIT 1
                ) AS ok_user
                """
        with self._sql.transaction() as tx:
            rows = tx.execute_query_mappings(
                sql_validate,
                {"ws": workspace_id, "did": int(domain_id), "tuid": target_user_id},
            )
            v = rows[0] if rows else None

            if not v or int(v.get("ok_domain") or 0) != 1:
                raise ServiceError("Domain not found", status_code=404)
            if int(v.get("ok_user") or 0) != 1:
                raise ServiceError("User not found in workspace", status_code=404)

            # Upsert mapping
            tx.execute_write(
                """
                INSERT INTO user_domain_mapping (domain_id, user_id, can_read, can_edit, created_at)
                VALUES (:did, :uid, :cr, :ce, CURRENT_TIMESTAMP)
                ON DUPLICATE KEY UPDATE
                can_read=VALUES(can_read),
                can_edit=VALUES(can_edit)
                """,
                {
                    "did": int(domain_id),
                    "uid": target_user_id,
                    "cr": 1 if can_read else 0,
                    "ce": 1 if can_edit else 0,
                },
            )

        return {"ok": True, "domain_id": int(domain_id), "user_id": target_user_id, "can_read": bool(can_read), "can_edit": bool(can_edit)}

    def remove_user(
        self,
        *,
        workspace_id: str,
        editor_user_id: str,
        domain_id: int,
        target_user_id: str,
    ) -> Dict[str, Any]:
        self._assert_can_edit_domain(workspace_id=workspace_id, user_id=editor_user_id, domain_id=domain_id)

        target_user_id = self._norm_user_id(target_user_id)

        with self._sql.transaction() as tx:
            ok_rows = tx.execute_query_mappings(
                "SELECT 1 FROM domain WHERE workspace_id=:ws AND id=:did AND is_active=1 LIMIT 1",
                {"ws": workspace_id, "did": int(domain_id)},
            )
            ok = ok_rows[0] if ok_rows else None
            if not ok:
                raise ServiceError("Domain not found", status_code=404)

            res = tx.execute_write(
                """
                DELETE udm
                FROM user_domain_mapping udm
                JOIN domain d ON d.id = udm.domain_id
                WHERE d.workspace_id=:ws
                AND udm.domain_id=:did
                AND udm.user_id=:uid
                """,
                {"ws": workspace_id, "did": int(domain_id), "uid": target_user_id},
            )

        return {"ok": True, "deleted": int(res or 0)}

    # ---------- batch apply (new) ----------

    def apply_changes(
        self,
        *,
        workspace_id: str,
        editor_user_id: str,
        domain_id: int,
        add: Optional[Iterable[Any]] = None,
        remove: Optional[Iterable[Any]] = None,
    ) -> Dict[str, Any]:
        """
        Apply batch changes from the frontend:
          { add: [{user_id, can_edit?}], remove: [user_id] }

        Notes:
          - add does UPSERT (and can be used to change role)
          - remove deletes mapping
          - can_read defaults to TRUE in this implementation (matches your existing route default)
        """
        self._assert_can_edit_domain(workspace_id=workspace_id, user_id=editor_user_id, domain_id=domain_id)

        add_rows = self._norm_add(add)
        remove_ids = self._norm_remove(remove)

        if not add_rows and not remove_ids:
            return {"ok": True, "added": 0, "removed": 0}

        # Validate domain belongs to workspace
        with self._sql.transaction() as tx:
            ok_rows = tx.execute_query_mappings(
                "SELECT 1 FROM domain WHERE workspace_id=:ws AND id=:did AND is_active=1 LIMIT 1",
                {"ws": workspace_id, "did": int(domain_id)},
            )
            ok_domain = ok_rows[0] if ok_rows else None
            if not ok_domain:
                raise ServiceError("Domain not found", status_code=404)

            # Validate all user_ids are in workspace (single query)
            check_user_ids = sorted({uid for uid, _ in add_rows} | set(remove_ids))
            if check_user_ids:
                placeholders = ",".join([f":u{i}" for i in range(len(check_user_ids))])
                params: Dict[str, Any] = {"ws": workspace_id}
                params.update({f"u{i}": uid for i, uid in enumerate(check_user_ids)})

                found = tx.execute_query_mappings(
                    f"""
                    SELECT uwm.user_id
                    FROM user_workspace_map uwm
                    WHERE uwm.workspace_id=:ws
                    AND uwm.user_id IN ({placeholders})
                    """,
                    params,
                )

                found_ids = {str(r["user_id"]) for r in found}
                missing = [uid for uid in check_user_ids if uid not in found_ids]
                if missing:
                    raise ServiceError(f"User(s) not found in workspace: {missing}", status_code=404)

            removed_ct = 0
            added_ct = 0

            # Remove in one statement
            if remove_ids:
                placeholders = ",".join([f":rid{i}" for i in range(len(remove_ids))])
                params = {"ws": workspace_id, "did": int(domain_id)}
                params.update({f"rid{i}": uid for i, uid in enumerate(remove_ids)})

                removed_ct = int(
                    tx.execute_write(
                        f"""
                        DELETE udm
                        FROM user_domain_mapping udm
                        JOIN domain d ON d.id = udm.domain_id
                        WHERE d.workspace_id=:ws
                        AND udm.domain_id=:did
                        AND udm.user_id IN ({placeholders})
                        """,
                        params,
                    )
                    or 0
                )

            # Add/upsert (role change supported)
            if add_rows:
                for uid, can_edit in add_rows:
                    tx.execute_write(
                        """
                        INSERT INTO user_domain_mapping (domain_id, user_id, can_read, can_edit, created_at)
                        VALUES (:did, :uid, 1, :ce, CURRENT_TIMESTAMP)
                        ON DUPLICATE KEY UPDATE
                        can_read=VALUES(can_read),
                        can_edit=VALUES(can_edit)
                        """,
                        {"did": int(domain_id), "uid": uid, "ce": 1 if can_edit else 0},
                    )
                added_ct = len(add_rows)

        return {"ok": True, "added": added_ct, "removed": removed_ct}
