# app/services/ai_suggest/domain_seeder.py
from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, Dict, List, Optional

from app.models.query.ai_suggest import SuggestModelResponse, SuggestRequest
from app.ports.sql_executor import ForgeQueryPort
from app.services.ai_suggest.edit_inspector import _column_ref_identity

logger = logging.getLogger(__name__)


def _workspace_table_ids_from_edits(edits: list[dict]) -> list[int]:
    table_ids: set[int] = set()
    for edit in edits or []:
        if not isinstance(edit, dict):
            continue
        op = str(edit.get("op") or "")
        if op not in {"addSelect", "addFilter", "addGroupBy", "addAggregate", "addSort"}:
            continue
        col = edit.get("col")
        if not isinstance(col, dict):
            continue
        wtid = col.get("workspaceTableId")
        try:
            if wtid is not None:
                table_ids.add(int(wtid))
        except (TypeError, ValueError):
            continue
    return sorted(table_ids)


def _placeholders(prefix: str, count: int) -> str:
    return ", ".join(f":{prefix}{i}" for i in range(count))


def infer_domain_from_columns(
    workspace_id: str,
    edits: list[dict],
    sql_executor: ForgeQueryPort,
) -> Optional[int]:
    table_ids = _workspace_table_ids_from_edits(edits)
    if not table_ids:
        return None

    placeholders = _placeholders("wtid", len(table_ids))
    sql = f"""
    SELECT DISTINCT dwt.domain_id
    FROM domain_workspace_table dwt
    WHERE dwt.workspace_id = :workspace_id
      AND dwt.workspace_table_id IN ({placeholders})
    """
    params: Dict[str, Any] = {"workspace_id": workspace_id}
    params.update({f"wtid{i}": int(v) for i, v in enumerate(table_ids)})

    rows = sql_executor.execute_query_mappings(sql, params)
    domain_ids: set[int] = set()
    for row in rows or []:
        try:
            domain_id = row.get("domain_id")
            if domain_id is not None:
                domain_ids.add(int(domain_id))
        except (TypeError, ValueError, AttributeError):
            continue

    if len(domain_ids) == 1:
        return next(iter(domain_ids))
    return None


class DomainSeeder:
    """Infers and seeds domain context into SQL JSON and edit lists."""

    def __init__(self, *, sql_executor: ForgeQueryPort) -> None:
        self._sql = sql_executor

    def infer_domain_safely(self, *, workspace_id: str, edits: list[dict]) -> Optional[int]:
        try:
            inferred = infer_domain_from_columns(
                workspace_id=workspace_id,
                edits=edits,
                sql_executor=self._sql,
            )
            logger.info(
                "AI suggest deterministic domain inference triggered=%s inferred_domain=%s",
                True,
                inferred,
            )
            return inferred
        except Exception as exc:
            logger.warning("AI suggest deterministic domain inference failed: %s", exc)
            return None

    def seed_sqljson_domain_if_missing(
        self,
        *,
        current_sqljson: Optional[Dict[str, Any]],
        suggest_request: SuggestRequest,
        validated: SuggestModelResponse,
    ) -> Optional[Dict[str, Any]]:
        has_set_domain = any(getattr(edit, "op", "") == "setDomain" for edit in validated.edits)
        if has_set_domain:
            return current_sqljson

        fallback_domain_id = self.fallback_domain_id(suggest_request)
        if fallback_domain_id is None:
            return current_sqljson

        if isinstance(current_sqljson, dict):
            seeded = deepcopy(current_sqljson)
            if seeded.get("domainId") is not None:
                return current_sqljson
            seeded["domainId"] = fallback_domain_id
            logger.info(
                "AI suggest seeded missing domainId from request context domainId=%s",
                fallback_domain_id,
            )
            return seeded

        logger.info(
            "AI suggest seeded missing domainId from request context domainId=%s",
            fallback_domain_id,
        )
        return {"domainId": fallback_domain_id}

    def fallback_domain_id(self, suggest_request: SuggestRequest) -> Optional[int]:
        domain_context = suggest_request.domainContext
        if domain_context is None:
            return None
        if domain_context.selectedDomainId is not None:
            return int(domain_context.selectedDomainId)
        if len(domain_context.domainCandidates) == 1:
            return int(domain_context.domainCandidates[0].domainId)
        return None

    def current_sqljson_domain_id(self, current_sqljson: Optional[Dict[str, Any]]) -> Optional[int]:
        if not isinstance(current_sqljson, dict):
            return None
        try:
            domain_id = current_sqljson.get("domainId")
            if domain_id is None:
                return None
            return int(domain_id)
        except (TypeError, ValueError):
            return None

    def columns_from_filter_tree(self, filter_node: Dict[str, Any]) -> List[Dict[str, Any]]:
        refs: List[Dict[str, Any]] = []
        seen: set[tuple] = set()

        def walk(node: Any) -> None:
            if not isinstance(node, dict):
                return
            node_type = str(node.get("type") or "")
            if node_type == "condition":
                field = node.get("field")
                if isinstance(field, dict) and str(field.get("columnName") or "").strip():
                    identity = _column_ref_identity(field)
                    if identity not in seen:
                        seen.add(identity)
                        refs.append(dict(field))
                return
            children = node.get("children")
            if isinstance(children, list):
                for child in children:
                    walk(child)

        walk(filter_node)
        return [{"field": ref, "alias": ref.get("columnName")} for ref in refs]
