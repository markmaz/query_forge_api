from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.exceptions.service_error import ServiceError
from app.services.domain.builder_column_feed_service import BuilderColumnFeedService, BuilderFeedQuery
from app.services.domain.domain_table_read_service import DomainTableReadService


class CohortBuilderVectorSqlJsonService:
    def build(
        self,
        *,
        workspace_id: str,
        user_id: str,
        demographics: Optional[Dict[str, Any]] = None,
        conditions: Optional[Dict[str, Any]] = None,
        procedures: Optional[Dict[str, Any]] = None,
        drugs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        demographics = demographics or {}
        conditions = conditions or {}
        procedures = procedures or {}
        drugs = drugs or {}

        domain = DomainTableReadService().get_domain(
            workspace_id=workspace_id, domain_name="Cohort Builder"
        )
        domain_id = domain.get("domain_id")
        if not domain_id:
            raise ServiceError("Cohort Builder domain not found", status_code=404)

        cols_payload = BuilderColumnFeedService().list_available_columns(
            BuilderFeedQuery(
                workspace_id=workspace_id,
                user_id=user_id,
                domain_id=int(domain_id),
                limit=5000,
                offset=0,
            )
        )
        rows = cols_payload.get("rows") or []

        col_map = self._build_column_map(rows)
        warnings: List[str] = []

        root = {"type": "group", "id": "root", "match": "and", "children": []}

        demo_group = self._build_demographics_group(demographics, rows, col_map, warnings)
        if demo_group:
            root["children"].append(demo_group)

        dx_year_group = self._build_dx_year_group(demographics, rows, col_map, warnings)
        if dx_year_group:
            root["children"].append(dx_year_group)

        conditions_group = self._build_conditions_group(conditions, rows, col_map, warnings)
        if conditions_group:
            root["children"].append(conditions_group)

        procedures_group = self._build_procedures_group(procedures, rows, col_map, warnings)
        if procedures_group:
            root["children"].append(procedures_group)

        drugs_group = self._build_drugs_group(drugs, rows, col_map, warnings)
        if drugs_group:
            root["children"].append(drugs_group)

        filters = root if root["children"] else None
        columns = self._build_projection(rows, warnings, filters=filters)

        sql_json: Dict[str, Any] = {
            "version": 1,
            "domainId": domain_id,
            "columns": columns,
            "filters": filters,
            "sorting": [],
            "distinct": True,
            "aggs": {"enabled": False, "metrics": [], "groupBy": []},
            "dataPrep": None,
            "crosswalks": {"a": None, "b": None, "c": None},
            "meta": {"warnings": warnings} if warnings else {},
        }

        return sql_json

    def _build_column_map(self, rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        by_name: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            name = r.get("columnName")
            if not name:
                continue
            if name in by_name and not r.get("isDefault"):
                continue
            by_name[name] = r
        return by_name

    def _aliases_used_by_filters(self, filters: Optional[Dict[str, Any]]) -> set[str]:
        used: set[str] = set()

        def walk(node: Any) -> None:
            if not isinstance(node, dict):
                return
            if node.get("type") == "group":
                for child in (node.get("children") or []):
                    walk(child)
                return
            if node.get("type") == "condition":
                field = node.get("field") or {}
                if isinstance(field, dict):
                    alias = (field.get("tableAlias") or "").strip().lower()
                    if alias:
                        used.add(alias)
                return

        walk(filters)
        return used

    def _build_projection(
        self,
        rows: List[Dict[str, Any]],
        warnings: List[str],
        *,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        order = [
            "cohort_key",
            "patient_gender",
            "patient_birth_year",
            "state",
        ]

        by_name: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            cn = r.get("columnName")
            if not cn:
                continue
            if cn not in by_name:
                by_name[cn] = r

        def _pick_by_alias(col_name: str, table_alias: str) -> Optional[Dict[str, Any]]:
            for r in rows:
                if (r.get("columnName") or "").lower() != col_name.lower():
                    continue
                if (r.get("tableAlias") or "").lower() == table_alias.lower():
                    return r
            return None

        out: List[Dict[str, Any]] = []
        for cn in order:
            r = by_name.get(cn)
            if not r:
                continue
            out.append(
                {
                    "workspaceTableId": r.get("workspaceTableId"),
                    "modelColumnId": r.get("modelColumnId"),
                    "columnName": cn,
                    "exprId": None,
                    "modelTableId": r.get("modelTableId"),
                    "modelTableName": r.get("modelTableName"),
                    "fullName": r.get("fullName"),
                    "dataType": r.get("dataType"),
                    "nullable": r.get("nullable"),
                    "alias": None,
                }
            )

        used_aliases = self._aliases_used_by_filters(filters)
        for table_alias in ("dx", "px", "ndc"):
            if table_alias not in used_aliases:
                continue

            code_row = _pick_by_alias("code", table_alias)
            if not code_row:
                warnings.append(f"Missing column: {table_alias}.code")
            else:
                out.append(
                    {
                        "workspaceTableId": code_row.get("workspaceTableId"),
                        "modelColumnId": code_row.get("modelColumnId"),
                        "columnName": "code",
                        "exprId": None,
                        "modelTableId": code_row.get("modelTableId"),
                        "modelTableName": code_row.get("modelTableName"),
                        "fullName": code_row.get("fullName"),
                        "dataType": code_row.get("dataType"),
                        "nullable": code_row.get("nullable"),
                        "alias": f"{table_alias}_code",
                    }
                )

            year_row = _pick_by_alias("year", table_alias)
            if not year_row:
                warnings.append(f"Missing column: {table_alias}.year")
            else:
                out.append(
                    {
                        "workspaceTableId": year_row.get("workspaceTableId"),
                        "modelColumnId": year_row.get("modelColumnId"),
                        "columnName": "year",
                        "exprId": None,
                        "modelTableId": year_row.get("modelTableId"),
                        "modelTableName": year_row.get("modelTableName"),
                        "fullName": year_row.get("fullName"),
                        "dataType": year_row.get("dataType"),
                        "nullable": year_row.get("nullable"),
                        "alias": f"{table_alias}_year",
                    }
                )

        return out


    def _col_key(self, col_map: Dict[str, Dict[str, Any]], name: str, warnings: List[str]) -> Optional[Dict[str, Any]]:
        hit = col_map.get(name)
        if not hit:
            warnings.append(f"Missing domain column: {name}")
            return None
        return {
            "workspaceTableId": hit.get("workspaceTableId"),
            "modelColumnId": hit.get("modelColumnId"),
            "columnName": name,
            "exprId": None,
        }

    def _col_key_for_alias(
        self,
        rows: List[Dict[str, Any]],
        column_name: str,
        table_alias: str,
        warnings: List[str],
    ) -> Optional[Dict[str, Any]]:
        for r in rows:
            if (r.get("columnName") or "").lower() != column_name.lower():
                continue
            if (r.get("tableAlias") or "").lower() == table_alias.lower():
                return {
                    "workspaceTableId": r.get("workspaceTableId"),
                    "modelColumnId": r.get("modelColumnId"),
                    "columnName": column_name,
                    "exprId": None,
                    "tableAlias": table_alias,
                }
        warnings.append(f"Missing domain column: {table_alias}.{column_name}")
        return None

    def _build_demographics_group(
        self,
        demographics: Dict[str, Any],
        rows: List[Dict[str, Any]],
        col_map: Dict[str, Dict[str, Any]],
        warnings: List[str],
    ) -> Optional[Dict[str, Any]]:
        children: List[Dict[str, Any]] = []

        age_bounds = self._parse_bounds(demographics, "age")
        if age_bounds:
            lower, upper = age_bounds
            current_year = datetime.utcnow().year
            birth_min = current_year - upper
            birth_max = current_year - lower
            field = self._col_key(col_map, "patient_birth_year", warnings)
            if field:
                children.append(
                    {
                        "type": "condition",
                        "id": "demo_age",
                        "field": field,
                        "op": "between",
                        "value": [birth_min, birth_max],
                    }
                )

        genders = demographics.get("gender") or demographics.get("genders") or []
        if isinstance(genders, str):
            genders = [g.strip() for g in genders.split(",") if g.strip()]
        if genders:
            norm = []
            for g in genders:
                if not g:
                    continue
                gg = str(g).strip().lower()
                if gg in ("male", "m"):
                    norm.append("M")
                elif gg in ("female", "f"):
                    norm.append("F")
                else:
                    norm.append(str(g).strip())
            norm = list(dict.fromkeys(norm))
            field = self._col_key(col_map, "patient_gender", warnings)
            if field and norm:
                children.append(
                    {"type": "condition", "id": "demo_gender", "field": field, "op": "in", "value": norm}
                )

        states = demographics.get("state") or demographics.get("states") or demographics.get("location") or []
        if isinstance(states, str):
            states = [s.strip() for s in states.split(",") if s.strip()]
        if states:
            state_field = self._col_key_for_alias(rows, "state", "patient", warnings)
            if not state_field:
                state_field = self._col_key(col_map, "state", warnings)
            if state_field:
                children.append(
                    {
                        "type": "condition",
                        "id": "demo_state",
                        "field": state_field,
                        "op": "in",
                        "value": list(dict.fromkeys([str(s).strip() for s in states if str(s).strip()])),
                    }
                )

        if not children:
            return None

        return {"type": "group", "id": "demographics", "match": "and", "children": children}

    def _build_dx_year_group(
        self,
        demographics: Dict[str, Any],
        rows: List[Dict[str, Any]],
        col_map: Dict[str, Dict[str, Any]],
        warnings: List[str],
    ) -> Optional[Dict[str, Any]]:
        dx_bounds = self._parse_bounds(demographics, "dx_year")
        if not dx_bounds:
            return None
        lower, upper = dx_bounds
        year_field = self._col_key_for_alias(rows, "year", "dx", warnings)
        if not year_field:
            return None
        return {
            "type": "group",
            "id": "dx_year",
            "match": "and",
            "children": [
                {
                    "type": "condition",
                    "id": "dx_year_range",
                    "field": year_field,
                    "op": "between",
                    "value": [lower, upper],
                }
            ],
        }

    def _build_conditions_group(
        self,
        payload: Dict[str, Any],
        rows: List[Dict[str, Any]],
        col_map: Dict[str, Dict[str, Any]],
        warnings: List[str],
    ) -> Optional[Dict[str, Any]]:
        codes, match = self._extract_codes(payload, warnings, label="conditions")
        if not codes:
            return None

        code_field = self._col_key_for_alias(rows, "code", "dx", warnings)
        if not code_field:
            return None

        code_conditions = []
        for idx, c in enumerate(codes):
            code_conditions.append(
                {
                    "type": "condition",
                    "id": f"cond_code_{idx}",
                    "field": code_field,
                    "op": "equals",
                    "value": c,
                }
            )

        children = [{"type": "group", "id": "cond_codes", "match": "or", "children": code_conditions}]

        return {"type": "group", "id": "conditions", "match": "and", "children": children}

    def _build_procedures_group(
        self,
        payload: Dict[str, Any],
        rows: List[Dict[str, Any]],
        col_map: Dict[str, Dict[str, Any]],
        warnings: List[str],
    ) -> Optional[Dict[str, Any]]:
        codes, match = self._extract_codes(payload, warnings, label="procedures")
        if not codes:
            return None

        code_field = self._col_key_for_alias(rows, "code", "px", warnings)
        if not code_field:
            return None

        code_conditions = []
        for idx, c in enumerate(codes):
            code_conditions.append(
                {
                    "type": "condition",
                    "id": f"proc_code_{idx}",
                    "field": code_field,
                    "op": "equals",
                    "value": c,
                }
            )

        children = [{"type": "group", "id": "proc_codes", "match": "or", "children": code_conditions}]

        return {"type": "group", "id": "procedures", "match": "and", "children": children}

    def _build_drugs_group(
        self,
        payload: Dict[str, Any],
        rows: List[Dict[str, Any]],
        col_map: Dict[str, Dict[str, Any]],
        warnings: List[str],
    ) -> Optional[Dict[str, Any]]:
        raw_codes, match = self._extract_codes(payload, warnings, label="drugs")
        if not raw_codes:
            return None

        codes: List[str] = []
        for c in raw_codes:
            parts = [p.strip() for p in str(c).split(",") if p.strip()]
            codes.extend(parts)
        codes = list(dict.fromkeys(codes))
        if len(codes) > 500:
            warnings.append("Drug NDC list capped at 500 codes.")
            codes = codes[:500]

        code_field = self._col_key_for_alias(rows, "code", "ndc", warnings)
        if not code_field:
            return None

        code_conditions = []
        for idx, c in enumerate(codes):
            code_conditions.append(
                {
                    "type": "condition",
                    "id": f"drug_code_{idx}",
                    "field": code_field,
                    "op": "equals",
                    "value": c,
                }
            )

        children = [{"type": "group", "id": "drug_codes", "match": "or", "children": code_conditions}]

        return {"type": "group", "id": "drugs", "match": "and", "children": children}

    def _parse_bounds(self, payload: Dict[str, Any], key: str) -> Optional[Tuple[int, int]]:
        if key in payload and isinstance(payload.get(key), dict):
            obj = payload.get(key) or {}
            lower = obj.get("lower_bound") or obj.get("lower") or obj.get("min") or obj.get("from")
            upper = obj.get("upper_bound") or obj.get("upper") or obj.get("max") or obj.get("to")
        else:
            lower = (
                payload.get(f"{key}_lower_bound")
                or payload.get(f"{key}_lower")
                or payload.get(f"{key}_min")
                or payload.get(f"{key}_from")
            )
            upper = (
                payload.get(f"{key}_upper_bound")
                or payload.get(f"{key}_upper")
                or payload.get(f"{key}_max")
                or payload.get(f"{key}_to")
            )

        if lower is None or upper is None:
            return None
        try:
            return int(lower), int(upper)
        except Exception:
            return None

    def _extract_codes(
        self, payload: Dict[str, Any], warnings: List[str], label: str
    ) -> Tuple[List[str], str]:
        codes: List[str] = []
        match = "and"
        seen_logic = set()
        for _, v in (payload or {}).items():
            if not isinstance(v, dict):
                continue
            code = v.get("code")
            if code:
                codes.append(str(code).strip())
            logic = (v.get("logic") or "").strip().lower()
            if logic in ("and", "or"):
                seen_logic.add(logic)
            if v.get("negation") is True:
                warnings.append(f"Negation not supported for {label}; ignoring negation.")

        codes = [c for c in codes if c]
        codes = list(dict.fromkeys(codes))

        if "and" in seen_logic and "or" in seen_logic:
            warnings.append(f"Mixed logic for {label}; defaulting to AND.")
            match = "and"
        elif "or" in seen_logic:
            match = "or"

        return codes, match
