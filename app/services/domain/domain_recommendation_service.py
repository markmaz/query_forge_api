from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config.llm_resolver import build_llm_client_for_role
from app.constants.llm_roles import LLMRole
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort
from app.services.domain.domain_admin_write_service import DomainAdminWriteService
from app.services.domain.domain_join_service import DomainJoinService
from app.services.domain.domain_table_write_service import DomainTableWriteService
from app.services.llm.llm_client import LLMClient


class DomainRecommendationService:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        llm_client: Optional[LLMClient] = None,
        domain_admin_write_service: Optional[DomainAdminWriteService] = None,
        domain_table_write_service: Optional[DomainTableWriteService] = None,
        domain_join_service: Optional[DomainJoinService] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._explicit_llm = llm_client is not None
        self._llm = llm_client or LLMClient()
        self._domain_admin_write_service = domain_admin_write_service or DomainAdminWriteService(sql=self._sql)
        self._domain_table_write_service = domain_table_write_service or DomainTableWriteService(sql=self._sql)
        self._domain_join_service = domain_join_service or DomainJoinService(sql=self._sql)

    def generate_recommendations(
        self,
        *,
        workspace_id: str,
        max_domains: int = 10,
        max_tables: int = 200,
        llm_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        max_domains = self._normalize_limit(max_domains, field="max_domains", minimum=1, maximum=20)
        max_tables = self._normalize_limit(max_tables, field="max_tables", minimum=1, maximum=500)

        table_rows = self._load_workspace_tables(workspace_id=workspace_id, max_tables=max_tables)
        warnings: List[str] = []
        if not table_rows:
            return {
                "workspace_id": workspace_id,
                "generated_at": self._utcnow(),
                "recommendations": [],
                "unassigned_tables": [],
                "warnings": ["No workspace tables are available for this workspace."],
            }

        truncated = len(table_rows) > max_tables
        tables_for_prompt = table_rows[:max_tables]
        if truncated:
            warnings.append(
                f"Only the first {max_tables} workspace tables were analyzed for this recommendation pass."
            )

        if workspace_id and not self._explicit_llm:
            resolved = build_llm_client_for_role(
                workspace_id=workspace_id,
                role=LLMRole.ENRICHMENT,
                llm_id_override=llm_id,
            )
            self._llm = resolved.client

        payload = self._llm.chat_json(
            system_prompt=self._system_prompt(),
            user_prompt=self._user_prompt(
                workspace_id=workspace_id,
                max_domains=max_domains,
                tables=tables_for_prompt,
            ),
            response_format=True,
            retry_invalid_schema=True,
            validator=self._is_valid_llm_payload,
            max_tokens=min(2600, 700 + (len(tables_for_prompt) * 28)),
        )

        normalized = self._normalize_recommendations(
            table_rows=tables_for_prompt,
            payload=payload,
        )
        return {
            "workspace_id": workspace_id,
            "generated_at": self._utcnow(),
            "recommendations": normalized["recommendations"],
            "unassigned_tables": normalized["unassigned_tables"],
            "warnings": warnings + normalized["warnings"],
        }

    def apply_recommendations(
        self,
        *,
        workspace_id: str,
        user_id: str,
        recommendations: Sequence[Mapping[str, Any]],
        mode: str = "create_only",
        column_name_policy: Optional[str] = None,
    ) -> Dict[str, Any]:
        mode_norm = str(mode or "create_only").strip().lower()
        if mode_norm not in {"create_only", "create_or_merge"}:
            raise ForgeError("mode must be create_only or create_or_merge", status_code=400)

        normalized = self._normalize_apply_payload(recommendations)
        table_id_by_name = self._load_workspace_table_id_map(workspace_id=workspace_id)
        duplicate_table_names = self._find_duplicate_table_names(normalized)
        if duplicate_table_names:
            raise ForgeError(
                "Each table may only be applied to one recommended domain at a time.",
                status_code=400,
                details={"duplicate_tables": duplicate_table_names},
            )

        created_domains: List[Dict[str, Any]] = []
        merged_domains: List[Dict[str, Any]] = []
        assigned_tables = 0
        created_joins = 0
        warnings: List[str] = []

        for item in normalized:
            domain_name = item["name"]
            existing_domain_id = self._load_domain_id_by_name(workspace_id=workspace_id, name=domain_name)
            if existing_domain_id is not None:
                if mode_norm == "create_only":
                    raise ForgeError(
                        f"Domain '{domain_name}' already exists in this workspace.",
                        status_code=409,
                    )
                domain_id = existing_domain_id
                merged_domains.append({"domain_id": int(domain_id), "name": domain_name})
            else:
                domain_row = self._domain_admin_write_service.create_domain(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    name=domain_name,
                    kind=item.get("kind"),
                    description=item.get("description"),
                    column_name_policy=column_name_policy,
                    bypass_permissions=True,
                )
                domain_id = int(domain_row.get("id") or 0)
                created_domains.append({"domain_id": domain_id, "name": domain_name})

            for table_name in item["table_names"]:
                workspace_table_id = table_id_by_name.get(table_name)
                if workspace_table_id is None:
                    raise ForgeError(
                        f"Workspace table '{table_name}' was not found.",
                        status_code=404,
                    )
                self._domain_table_write_service.add_or_update_table(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    domain_id=domain_id,
                    workspace_table_id=workspace_table_id,
                    bypass_permissions=True,
                )
                assigned_tables += 1

            join_result = self._create_inferred_joins(
                workspace_id=workspace_id,
                domain_id=domain_id,
                table_names=item["table_names"],
                table_id_by_name=table_id_by_name,
            )
            created_joins += int(join_result["created_joins"])
            if join_result["warning"]:
                warnings.append(join_result["warning"])

        if merged_domains:
            warnings.append(
                f"Merged recommendations into {len(merged_domains)} existing domain"
                f"{'' if len(merged_domains) == 1 else 's'}."
            )

        return {
            "created_domains": created_domains,
            "merged_domains": merged_domains,
            "assigned_tables": assigned_tables,
            "created_joins": created_joins,
            "warnings": warnings,
        }

    def _load_workspace_tables(self, *, workspace_id: str, max_tables: int) -> List[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              wt.id,
              wt.table_name,
              wt.full_name,
              wt.description
            FROM workspace_table wt
            WHERE wt.workspace_id = :ws
            ORDER BY wt.table_name ASC
            LIMIT :limit_plus_one
            """,
            {"ws": workspace_id, "limit_plus_one": int(max_tables) + 1},
        )
        return [dict(row) for row in rows]

    def _load_workspace_table_id_map(self, *, workspace_id: str) -> Dict[str, int]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT wt.id, wt.table_name
            FROM workspace_table wt
            WHERE wt.workspace_id = :ws
            """,
            {"ws": workspace_id},
        )
        return {
            str(row.get("table_name") or "").strip(): int(row.get("id"))
            for row in rows
            if str(row.get("table_name") or "").strip() and row.get("id") is not None
        }

    def _load_domain_id_by_name(self, *, workspace_id: str, name: str) -> Optional[int]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT d.id
            FROM domain d
            WHERE d.workspace_id = :ws
              AND LOWER(d.name) = LOWER(:name)
            LIMIT 1
            """,
            {"ws": workspace_id, "name": name},
        )
        if not rows:
            return None
        return int(rows[0].get("id") or 0) or None

    def _load_workspace_columns(self, *, workspace_table_ids: Sequence[int]) -> Dict[int, List[str]]:
        ids = sorted({int(value) for value in workspace_table_ids if int(value) > 0})
        if not ids:
            return {}

        placeholders = ", ".join(f":wtid_{index}" for index in range(len(ids)))
        params = {f"wtid_{index}": value for index, value in enumerate(ids)}
        rows = self._sql.execute_query_mappings(
            f"""
            SELECT workspace_table_id, column_name
            FROM workspace_column
            WHERE workspace_table_id IN ({placeholders})
            """,
            params,
        )

        out: Dict[int, List[str]] = {}
        for row in rows:
            table_id = row.get("workspace_table_id")
            column_name = str(row.get("column_name") or "").strip()
            if table_id is None or not column_name:
                continue
            out.setdefault(int(table_id), []).append(column_name)
        return out

    def _create_inferred_joins(
        self,
        *,
        workspace_id: str,
        domain_id: int,
        table_names: Sequence[str],
        table_id_by_name: Mapping[str, int],
    ) -> Dict[str, Any]:
        table_ids = [table_id_by_name[name] for name in table_names if name in table_id_by_name]
        if len(table_ids) < 2:
            return {"created_joins": 0, "warning": None}

        columns_by_table_id = self._load_workspace_columns(workspace_table_ids=table_ids)
        if not columns_by_table_id:
            return {"created_joins": 0, "warning": None}

        root_table_id = table_ids[0]
        connected = {root_table_id}
        remaining = [table_id for table_id in table_ids[1:] if table_id != root_table_id]
        sort_order = 0
        created = 0

        while remaining:
            best_candidate: Optional[Dict[str, Any]] = None
            for target_table_id in remaining:
                for source_table_id in connected:
                    candidate = self._best_join_candidate(
                        source_table_id=source_table_id,
                        target_table_id=target_table_id,
                        columns_by_table_id=columns_by_table_id,
                    )
                    if candidate is None:
                        continue
                    if best_candidate is None or int(candidate["score"]) > int(best_candidate["score"]):
                        best_candidate = candidate

            if best_candidate is None:
                break

            self._domain_join_service.create_join(
                workspace_id=workspace_id,
                domain_id=int(domain_id),
                from_workspace_table_id=int(best_candidate["source_table_id"]),
                to_workspace_table_id=int(best_candidate["target_table_id"]),
                join_type="LEFT",
                join_spec={
                    "on": [
                        {
                            "left": {
                                "workspaceTableId": int(best_candidate["source_table_id"]),
                                "columnName": str(best_candidate["column_name"]),
                            },
                            "op": "=",
                            "right": {
                                "workspaceTableId": int(best_candidate["target_table_id"]),
                                "columnName": str(best_candidate["column_name"]),
                            },
                        }
                    ]
                },
                sort_order=sort_order,
            )
            created += 1
            sort_order += 1
            connected.add(int(best_candidate["target_table_id"]))
            remaining = [
                table_id for table_id in remaining if table_id != int(best_candidate["target_table_id"])
            ]

        warning = None
        if remaining:
            unresolved = [name for name in table_names if table_id_by_name.get(name) in remaining]
            warning = (
                "Some recommended tables were assigned but could not be auto-linked in the graph: "
                + ", ".join(unresolved)
                + "."
            )

        return {"created_joins": created, "warning": warning}

    def _best_join_candidate(
        self,
        *,
        source_table_id: int,
        target_table_id: int,
        columns_by_table_id: Mapping[int, Sequence[str]],
    ) -> Optional[Dict[str, Any]]:
        source_columns = {
            str(column).strip().lower(): str(column).strip()
            for column in columns_by_table_id.get(int(source_table_id), [])
            if str(column).strip()
        }
        target_columns = {
            str(column).strip().lower(): str(column).strip()
            for column in columns_by_table_id.get(int(target_table_id), [])
            if str(column).strip()
        }
        shared = sorted(set(source_columns.keys()) & set(target_columns.keys()))
        best: Optional[Dict[str, Any]] = None
        for column_name in shared:
            score = self._join_column_score(column_name)
            if score <= 0:
                continue
            candidate = {
                "source_table_id": int(source_table_id),
                "target_table_id": int(target_table_id),
                "column_name": source_columns[column_name],
                "score": score,
            }
            if best is None or int(candidate["score"]) > int(best["score"]):
                best = candidate
        return best

    @staticmethod
    def _join_column_score(column_name: str) -> int:
        normalized = str(column_name or "").strip().lower()
        if not normalized:
            return 0
        if normalized in {
            "created_at",
            "updated_at",
            "deleted_at",
            "description",
            "name",
            "type",
            "status",
            "sort_order",
            "position",
        }:
            return 0
        if normalized == "id":
            return 30
        if normalized.startswith("k_"):
            return 95
        if normalized.endswith("_id"):
            return 100
        if normalized.endswith("_key") or normalized == "key":
            return 85
        if normalized.endswith("_code") or normalized == "code":
            return 55
        if normalized.endswith("_year") or normalized.endswith("_date"):
            return 25
        return 10

    @staticmethod
    def _normalize_limit(value: Any, *, field: str, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except Exception as exc:
            raise ForgeError(f"{field} must be an integer", status_code=400) from exc
        if parsed < minimum or parsed > maximum:
            raise ForgeError(
                f"{field} must be between {minimum} and {maximum}",
                status_code=400,
            )
        return parsed

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are organizing analytics warehouse tables into business domains for a visual domain builder. "
            "Use only the tables provided. Prefer 5 to 12 business-friendly domains unless the requested max_domains is smaller. "
            "Group tables by business meaning, not just schema prefixes. "
            "Return strict JSON with keys: domains (array), unassigned_tables (array of strings). "
            "Each domain must contain: name (string), description (string), table_names (array of strings), "
            "confidence (number 0 to 1), rationale (array of short strings). "
            "Do not invent tables. Do not include markdown."
        )

    @staticmethod
    def _user_prompt(
        *,
        workspace_id: str,
        max_domains: int,
        tables: Sequence[Mapping[str, Any]],
    ) -> str:
        compact = [
            {
                "table_name": str(row.get("table_name") or "").strip(),
                "full_name": str(row.get("full_name") or "").strip() or None,
                "description": str(row.get("description") or "").strip() or None,
            }
            for row in tables
            if str(row.get("table_name") or "").strip()
        ]
        return json.dumps(
            {
                "workspace_id": workspace_id,
                "max_domains": max_domains,
                "tables": compact,
                "instructions": [
                    "Return a best-guess draft domain model for review.",
                    "Assign each table to at most one domain when possible.",
                    "Use concise business names like Student Demographics And Enrollment.",
                    "Put uncertain tables in unassigned_tables instead of forcing a weak grouping.",
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _is_valid_llm_payload(payload: Dict[str, Any]) -> bool:
        domains = payload.get("domains")
        if not isinstance(domains, list):
            return False
        for item in domains:
            if not isinstance(item, dict):
                return False
            if not str(item.get("name") or "").strip():
                return False
            if not isinstance(item.get("table_names"), list):
                return False
        unassigned = payload.get("unassigned_tables")
        if unassigned is not None and not isinstance(unassigned, list):
            return False
        return True

    def _normalize_recommendations(
        self,
        *,
        table_rows: Sequence[Mapping[str, Any]],
        payload: Mapping[str, Any],
    ) -> Dict[str, Any]:
        known_tables = {
            str(row.get("table_name") or "").strip()
            for row in table_rows
            if str(row.get("table_name") or "").strip()
        }
        recommendations: List[Dict[str, Any]] = []
        warnings: List[str] = []
        assigned_counter: Counter[str] = Counter()

        for idx, item in enumerate(payload.get("domains") or []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue

            seen_local: set[str] = set()
            table_names: List[str] = []
            unknown_tables: List[str] = []
            for raw_name in item.get("table_names") or []:
                table_name = str(raw_name or "").strip()
                if not table_name or table_name in seen_local:
                    continue
                seen_local.add(table_name)
                if table_name not in known_tables:
                    unknown_tables.append(table_name)
                    continue
                table_names.append(table_name)
                assigned_counter[table_name] += 1

            if unknown_tables:
                warnings.append(
                    f"Recommendation '{name}' referenced unknown tables: {', '.join(sorted(unknown_tables))}."
                )
            if not table_names:
                warnings.append(f"Recommendation '{name}' did not contain any valid workspace tables and was dropped.")
                continue

            confidence = self._normalize_confidence(item.get("confidence"))
            rationale = self._normalize_rationale(item.get("rationale"))
            recommendations.append(
                {
                    "key": self._slugify(name, fallback=f"domain_{idx + 1}"),
                    "name": name,
                    "description": str(item.get("description") or "").strip() or "Suggested domain grouping.",
                    "table_names": table_names,
                    "confidence": confidence,
                    "rationale": rationale,
                }
            )

        duplicate_tables = {table for table, count in assigned_counter.items() if count > 1}
        if duplicate_tables:
            warnings.append(
                "Some tables were assigned to multiple recommended domains: "
                + ", ".join(sorted(duplicate_tables))
                + "."
            )

        for item in recommendations:
            item["needs_review"] = (
                item["confidence"] < 0.7
                or any(table_name in duplicate_tables for table_name in item["table_names"])
            )

        recommendations.sort(
            key=lambda item: (
                item["needs_review"],
                -float(item.get("confidence") or 0.0),
                str(item.get("name") or "").lower(),
            )
        )

        assigned_tables = set(assigned_counter.keys())
        unassigned_tables = [table for table in sorted(known_tables) if table not in assigned_tables]
        return {
            "recommendations": recommendations,
            "unassigned_tables": unassigned_tables,
            "warnings": warnings,
        }

    @staticmethod
    def _normalize_apply_payload(
        recommendations: Sequence[Mapping[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not isinstance(recommendations, (list, tuple)) or not recommendations:
            raise ForgeError("recommendations must be a non-empty list", status_code=400)

        out: List[Dict[str, Any]] = []
        for item in recommendations:
            if not isinstance(item, Mapping):
                raise ForgeError("Each recommendation must be an object", status_code=400)
            name = str(item.get("name") or "").strip()
            if not name:
                raise ForgeError("Each recommendation requires a name", status_code=400)
            table_names_raw = item.get("table_names")
            if not isinstance(table_names_raw, list):
                raise ForgeError(f"Recommendation '{name}' requires table_names", status_code=400)
            seen: set[str] = set()
            table_names: List[str] = []
            for raw in table_names_raw:
                table_name = str(raw or "").strip()
                if not table_name or table_name in seen:
                    continue
                seen.add(table_name)
                table_names.append(table_name)
            if not table_names:
                raise ForgeError(
                    f"Recommendation '{name}' must include at least one table.",
                    status_code=400,
                )
            out.append(
                {
                    "name": name,
                    "description": str(item.get("description") or "").strip() or None,
                    "kind": str(item.get("kind") or "").strip() or None,
                    "table_names": table_names,
                }
            )
        return out

    @staticmethod
    def _find_duplicate_table_names(recommendations: Sequence[Mapping[str, Any]]) -> List[str]:
        counts: Counter[str] = Counter()
        for item in recommendations:
            for table_name in item.get("table_names") or []:
                counts[str(table_name)] += 1
        return sorted([table_name for table_name, count in counts.items() if count > 1])

    @staticmethod
    def _normalize_confidence(value: Any) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return 0.5
        if parsed < 0.0:
            return 0.0
        if parsed > 1.0:
            return 1.0
        return round(parsed, 3)

    @staticmethod
    def _normalize_rationale(value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        out: List[str] = []
        for item in value:
            text = str(item or "").strip()
            if text:
                out.append(text[:240])
        return out[:4]

    @staticmethod
    def _slugify(value: str, *, fallback: str) -> str:
        token = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
        return token or fallback

    @staticmethod
    def _utcnow() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
