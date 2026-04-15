from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.exceptions.forge_error import ForgeError
from app.services.domain_resolver import DomainPlan, DomainResolver


class QueryForgePlanInspector:
    def __init__(self, domain_resolver: DomainResolver) -> None:
        self._domains = domain_resolver

    def select_two_phase_key_column(
        self,
        *,
        q: Dict[str, Any],
        plan: DomainPlan,
        primary_id: int,
        filter_only_table_ids: set[int],
    ) -> Optional[str]:
        candidates: List[str] = []
        candidates.extend(
            self.primary_join_key_candidates(
                plan=plan,
                primary_id=primary_id,
                filter_only_table_ids=filter_only_table_ids,
            )
        )
        candidates.extend(
            self.primary_query_key_candidates(
                q=q,
                primary_id=primary_id,
            )
        )

        catalog = self.load_domain_column_catalog(plan)
        primary_columns = {
            col
            for (wt_id, col), _meta in catalog.items()
            if int(wt_id) == int(primary_id) and col
        }
        if primary_columns:
            preferred = [
                "patient_id",
                "k_person",
                "k_staff",
                "staff_unique_id",
                "local_staff_id",
                "k_student",
                "student_unique_id",
                "school_id",
                "id",
                "oid",
            ]
            for name in preferred:
                if name in primary_columns:
                    candidates.append(name)
            for name in sorted(primary_columns):
                if self.looks_like_identifier_column(name):
                    candidates.append(name)

        seen: set[str] = set()
        for raw in candidates:
            col = str(raw or "").strip().lower()
            if not col or col in seen:
                continue
            seen.add(col)
            if not self.looks_like_identifier_column(col):
                continue
            if primary_columns and col not in primary_columns:
                continue
            return col
        return None

    def primary_join_key_candidates(
        self,
        *,
        plan: DomainPlan,
        primary_id: int,
        filter_only_table_ids: set[int],
    ) -> List[str]:
        out: List[str] = []
        for wt_id in sorted(filter_only_table_ids):
            try:
                path = self._domains.get_join_path(plan, int(wt_id))
            except ForgeError:
                continue
            for edge in path:
                if int(edge.from_workspace_table_id) != int(primary_id):
                    continue
                spec = edge.join_spec or {}
                on_list = spec.get("on") or []
                if not isinstance(on_list, list):
                    continue
                for item in on_list:
                    if not isinstance(item, dict):
                        continue
                    left = item.get("left") or {}
                    col = str((left.get("columnName") or left.get("col") or "")).strip().lower()
                    if col and "." not in col:
                        out.append(col)
        return out

    @staticmethod
    def primary_query_key_candidates(*, q: Dict[str, Any], primary_id: int) -> List[str]:
        out: List[str] = []
        for c in list(q.get("columns") or []):
            if not isinstance(c, dict):
                continue
            cn = str(c.get("columnName") or "").strip().lower()
            wt = c.get("workspaceTableId")
            if not cn or "." in cn:
                continue
            try:
                wt_ok = wt is None or int(wt) == int(primary_id)
            except (TypeError, ValueError):
                wt_ok = False
            if wt_ok:
                out.append(cn)

        for s in list(q.get("sorting") or []):
            if not isinstance(s, dict):
                continue
            col = s.get("col") if "col" in s else s.get("columnName")
            if not isinstance(col, dict):
                continue
            cn = str(col.get("columnName") or "").strip().lower()
            wt = col.get("workspaceTableId")
            if not cn or "." in cn:
                continue
            try:
                wt_ok = wt is None or int(wt) == int(primary_id)
            except (TypeError, ValueError):
                wt_ok = False
            if wt_ok:
                out.append(cn)
        return out

    @staticmethod
    def looks_like_identifier_column(column_name: str) -> bool:
        col = str(column_name or "").strip().lower()
        if not col:
            return False
        if col in {"id", "oid", "k_person", "k_staff", "k_student"}:
            return True
        if col.startswith("k_"):
            return True
        if col.endswith("_id") or col.endswith("_key"):
            return True
        if "unique_id" in col:
            return True
        return False

    def load_domain_column_catalog(self, plan: DomainPlan) -> Dict[tuple[int, str], Dict[str, Any]]:
        ws_id = getattr(self._domains, "_workspace_id", None)
        sql = getattr(self._domains, "_sql", None)
        if not ws_id or sql is None or not hasattr(sql, "execute_query_mappings"):
            return {}
        table_ids = sorted({int(t.workspace_table_id) for t in (plan.tables or [])})
        if not table_ids:
            return {}
        in_clause = ", ".join(str(int(tid)) for tid in table_ids)
        sql_text = f"""
            SELECT
              wc.workspace_table_id,
              wc.column_name,
              LOWER(COALESCE(wc.data_type, '')) AS data_type
            FROM workspace_column wc
            JOIN workspace_table wt
              ON wt.id = wc.workspace_table_id
            WHERE wt.workspace_id = :ws
              AND wc.workspace_table_id IN ({in_clause})
        """
        rows = sql.execute_query_mappings(sql_text, {"ws": ws_id}) or []
        catalog: Dict[tuple[int, str], Dict[str, Any]] = {}
        for row in rows:
            try:
                wt_id = int(row.get("workspace_table_id"))
            except (TypeError, ValueError):
                continue
            col_name = str(row.get("column_name") or "").strip().lower()
            if not col_name:
                continue
            catalog[(wt_id, col_name)] = {"data_type": str(row.get("data_type") or "").strip().lower()}
        return catalog

    @staticmethod
    def workspace_table_ids_with_column(
        plan: DomainPlan,
        *,
        column_name: str,
        column_catalog: Optional[Dict[tuple[int, str], Dict[str, Any]]] = None,
    ) -> set[int]:
        wanted = str(column_name or "").strip().lower()
        if not wanted:
            return set()
        catalog = column_catalog or {}
        out: set[int] = set()
        for t in (plan.tables or []):
            wt_id = int(t.workspace_table_id)
            if (wt_id, wanted) in catalog:
                out.add(wt_id)
        return out
