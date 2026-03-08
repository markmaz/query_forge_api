from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort


class _DomainUserStore:
    def __init__(self, *, sql: ForgeQueryPort) -> None:
        self._sql = sql

    def user_can_edit_domain(self, *, workspace_id: str, user_id: str, domain_id: int) -> bool:
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
            {"ws": workspace_id, "did": int(domain_id), "uid": user_id},
        )
        return bool(rows)


class DomainUserWriteService:
    """
    Domain <-> users mapping (user_domain_mapping)

    Permission: requires can_edit=1 on the domain.

    Supports:
      - upsert_user(...) / remove_user(...) (single)
      - apply_changes(..., add=[...], remove=[...]) (batch)
    """

    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._store = _DomainUserStore(sql=self._sql)

    def _assert_can_edit_domain(self, *, workspace_id: str, user_id: str, domain_id: int) -> None:
        if not self._store.user_can_edit_domain(workspace_id=workspace_id, user_id=user_id, domain_id=domain_id):
            raise ForgeError("You do not have edit permission for this domain.", status_code=403)

    @staticmethod
    def _norm_user_id(v: Any) -> str:
        s = (str(v) if v is not None else "").strip()
        if not s:
            raise ForgeError("user_id is required", status_code=400)
        return s

    @staticmethod
    def _coerce_bool(v: Any, *, field: str) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, str)):
            text = str(v).strip().lower()
            if text in {"1", "true", "yes", "y", "on"}:
                return True
            if text in {"0", "false", "no", "n", "off", ""}:
                return False
        raise ForgeError(f"'{field}' must be boolean", status_code=400)

    @staticmethod
    def _norm_remove(vals: Optional[Iterable[Any]]) -> List[str]:
        if vals is None:
            return []
        if not isinstance(vals, (list, tuple)):
            raise ForgeError("'remove' must be a list of user_id strings", status_code=400)

        out: List[str] = [DomainUserWriteService._norm_user_id(v) for v in vals]

        seen = set()
        deduped: List[str] = []
        for user_id in out:
            if user_id in seen:
                continue
            seen.add(user_id)
            deduped.append(user_id)
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
            raise ForgeError("'add' must be a list of objects", status_code=400)

        out: List[Tuple[str, bool]] = []
        for item in vals:
            if not isinstance(item, dict):
                raise ForgeError("'add' must contain objects like {user_id, can_edit?}", status_code=400)
            uid = DomainUserWriteService._norm_user_id(item.get("user_id"))
            can_edit = DomainUserWriteService._coerce_bool(item.get("can_edit", False), field="can_edit")
            out.append((uid, can_edit))

        # dedupe by user_id, keep latest can_edit value while preserving first-seen order
        order: List[str] = []
        index: Dict[str, bool] = {}
        for uid, can_edit in out:
            if uid not in index:
                order.append(uid)
            index[uid] = can_edit
        return [(uid, index[uid]) for uid in order]

    def upsert_user(
        self,
        *,
        workspace_id: str,
        editor_user_id: str,
        domain_id: int,
        tarrequire_user_id: str,
        can_read: bool = True,
        can_edit: bool = False,
    ) -> Dict[str, Any]:
        self._assert_can_edit_domain(workspace_id=workspace_id, user_id=editor_user_id, domain_id=domain_id)
        tarrequire_user_id = self._norm_user_id(tarrequire_user_id)

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
                {"ws": workspace_id, "did": int(domain_id), "tuid": tarrequire_user_id},
            )
            check = rows[0] if rows else None

            if not check or int(check.get("ok_domain") or 0) != 1:
                raise ForgeError("Domain not found", status_code=404)
            if int(check.get("ok_user") or 0) != 1:
                raise ForgeError("User not found in workspace", status_code=404)

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
                    "uid": tarrequire_user_id,
                    "cr": 1 if can_read else 0,
                    "ce": 1 if can_edit else 0,
                },
            )

        return {
            "ok": True,
            "domain_id": int(domain_id),
            "user_id": tarrequire_user_id,
            "can_read": bool(can_read),
            "can_edit": bool(can_edit),
        }

    def remove_user(
        self,
        *,
        workspace_id: str,
        editor_user_id: str,
        domain_id: int,
        tarrequire_user_id: str,
    ) -> Dict[str, Any]:
        self._assert_can_edit_domain(workspace_id=workspace_id, user_id=editor_user_id, domain_id=domain_id)
        tarrequire_user_id = self._norm_user_id(tarrequire_user_id)

        with self._sql.transaction() as tx:
            exists_rows = tx.execute_query_mappings(
                "SELECT 1 FROM domain WHERE workspace_id=:ws AND id=:did AND is_active=1 LIMIT 1",
                {"ws": workspace_id, "did": int(domain_id)},
            )
            if not (exists_rows and exists_rows[0]):
                raise ForgeError("Domain not found", status_code=404)

            deleted = tx.execute_write(
                """
                DELETE udm
                FROM user_domain_mapping udm
                JOIN domain d ON d.id = udm.domain_id
                WHERE d.workspace_id=:ws
                  AND udm.domain_id=:did
                  AND udm.user_id=:uid
                """,
                {"ws": workspace_id, "did": int(domain_id), "uid": tarrequire_user_id},
            )

        return {"ok": True, "deleted": int(deleted or 0)}

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
        Apply batch changes:
          { add: [{user_id, can_edit?}], remove: [user_id] }

        - add performs upsert and can change can_edit
        - remove deletes mapping rows
        """
        self._assert_can_edit_domain(workspace_id=workspace_id, user_id=editor_user_id, domain_id=domain_id)

        add_rows = self._norm_add(add)
        remove_ids = self._norm_remove(remove)

        if not add_rows and not remove_ids:
            return {"ok": True, "added": 0, "removed": 0}

        with self._sql.transaction() as tx:
            domain_check_rows = tx.execute_query_mappings(
                "SELECT 1 AS ok_domain FROM domain WHERE workspace_id=:ws AND id=:did AND is_active=1 LIMIT 1",
                {"ws": workspace_id, "did": int(domain_id)},
            )
            if not (domain_check_rows and domain_check_rows[0]):
                raise ForgeError("Domain not found", status_code=404)

            check_user_ids = sorted({uid for uid, _ in add_rows} | set(remove_ids))
            if check_user_ids:
                placeholders = ",".join(f":u{i}" for i in range(len(check_user_ids)))
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
                found_ids = {str(row["user_id"]) for row in found}
                missing = [uid for uid in check_user_ids if uid not in found_ids]
                if missing:
                    raise ForgeError(f"User(s) not found in workspace: {missing}", status_code=404)

            removed_count = 0
            if remove_ids:
                placeholders = ",".join(f":rid{i}" for i in range(len(remove_ids)))
                params = {"ws": workspace_id, "did": int(domain_id)}
                params.update({f"rid{i}": uid for i, uid in enumerate(remove_ids)})
                removed_count = int(
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

        return {"ok": True, "added": len(add_rows), "removed": removed_count}
