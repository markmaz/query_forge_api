from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import METADATA_SOURCE_MODE
from app.ports.sql_executor import ForgeQueryPort


@dataclass(frozen=True)
class _Hit:
    workspace_table_id: int
    score: float
    table_name: Optional[str]


class DomainResolverService:
    def __init__(
        self,
        db_session: Optional[ForgeQueryPort] = None,
        *,
        sql: Optional[ForgeQueryPort] = None,
        metadata_mode: Optional[str] = None,
    ) -> None:
        self._sql = sql or db_session or ForgeMetaSQL()
        self._metadata_mode = str(metadata_mode or METADATA_SOURCE_MODE or "legacy").strip().lower() or "legacy"

    def resolve_from_table_hits(
        self,
        *,
        workspace_id: str,
        table_hits: List[Dict[str, Any]],
        max_domains: int = 3,
        min_coverage: float = 0.60,
    ) -> Dict[str, Any]:
        hits = _normalize_hits(table_hits)
        hit_table_ids = {hit.workspace_table_id for hit in hits}
        total_hits = len(hit_table_ids)

        if total_hits == 0:
            return {
                "recommended": [],
                "uncovered_tables": [],
                "notes": ["No table hits provided."],
            }

        score_map = {hit.workspace_table_id: hit.score for hit in hits}
        name_map = {hit.workspace_table_id: hit.table_name for hit in hits if hit.table_name}

        mapping_rows = self._fetch_domain_mappings(workspace_id, hit_table_ids)
        domain_map: Dict[int, set[int]] = {}
        domain_names: Dict[int, str] = {}
        primary_map: Dict[int, bool] = {}
        for row in mapping_rows:
            domain_id = row.get("domain_id")
            table_id = row.get("workspace_table_id")
            if domain_id is None or table_id is None:
                continue
            domain_id = int(domain_id)
            table_id = int(table_id)
            domain_map.setdefault(domain_id, set()).add(table_id)
            if row.get("domain_name"):
                domain_names[domain_id] = str(row.get("domain_name"))
            if int(row.get("is_primary") or 0) == 1:
                primary_map[domain_id] = True

        recommended = []
        for domain_id, covered in domain_map.items():
            covered_hits = len(covered & hit_table_ids)
            if covered_hits == 0:
                continue
            coverage = covered_hits / total_hits
            strength = sum(score_map.get(tid, 0.0) for tid in covered)
            bonus = 0.05 if primary_map.get(domain_id) else 0.0
            missing = sorted(hit_table_ids - covered)
            recommended.append(
                {
                    "domain_id": domain_id,
                    "domain_name": domain_names.get(domain_id),
                    "coverage": round(coverage, 4),
                    "strength": round(strength, 6),
                    "covered_table_ids": sorted(covered),
                    "missing_table_ids": missing,
                    "reasons": [f"covers {covered_hits}/{total_hits} hit tables"],
                    "_rank_strength": strength + bonus,
                }
            )

        recommended.sort(key=lambda item: (-item["coverage"], -item["_rank_strength"]))
        recommended = recommended[: max(0, int(max_domains))]
        for item in recommended:
            item.pop("_rank_strength", None)

        uncovered_tables = self._fetch_uncovered_tables(workspace_id, hit_table_ids, name_map)

        notes: List[str] = []
        if recommended:
            best_coverage = recommended[0]["coverage"]
            if best_coverage < float(min_coverage):
                notes.append(
                    "No domain covers enough of the vector hits; consider creating a new domain or updating mappings."
                )
        else:
            notes.append("No domains mapped to the vector hits.")

        return {
            "recommended": recommended,
            "uncovered_tables": uncovered_tables,
            "notes": notes,
        }

    def _fetch_domain_mappings(self, workspace_id: str, table_ids: Iterable[int]) -> List[Dict[str, Any]]:
        table_ids = list(table_ids)
        if not table_ids:
            return []
        placeholders = _placeholders("tid", len(table_ids))
        sql = f"""
        SELECT
          dwt.domain_id,
          dwt.workspace_table_id,
          dwt.is_primary,
          d.name AS domain_name
        FROM domain_workspace_table dwt
        JOIN domain d
          ON d.id = dwt.domain_id
        WHERE d.workspace_id = :workspace_id
          AND dwt.workspace_table_id IN ({placeholders})
        """
        params = {"workspace_id": workspace_id}
        params.update({f"tid{idx}": int(val) for idx, val in enumerate(table_ids)})
        return self._sql.execute_query_mappings(sql, params)

    def _fetch_uncovered_tables(
        self,
        workspace_id: str,
        table_ids: Iterable[int],
        name_map: Mapping[int, str],
    ) -> List[Dict[str, Any]]:
        table_ids = list(table_ids)
        if not table_ids:
            return []
        placeholders = _placeholders("uid", len(table_ids))
        if self._metadata_mode == "workspace":
            sql = f"""
            SELECT
              wt.id AS workspace_table_id,
              COALESCE(NULLIF(wt.source_table_name, ''), wt.table_name, wt.full_name) AS table_name
            FROM workspace_table wt
            LEFT JOIN domain_workspace_table dwt
              ON dwt.workspace_table_id = wt.id
            LEFT JOIN domain d
              ON d.id = dwt.domain_id
             AND d.workspace_id = :workspace_id
            WHERE wt.workspace_id = :workspace_id
              AND wt.id IN ({placeholders})
              AND d.id IS NULL
            """
        else:
            sql = f"""
            SELECT
              wt.id AS workspace_table_id,
              COALESCE(mt.source_table_name, mt.name, wt.table_name, wt.full_name) AS table_name
            FROM workspace_table wt
            LEFT JOIN model_table mt
              ON mt.id = wt.model_table_id
            LEFT JOIN domain_workspace_table dwt
              ON dwt.workspace_table_id = wt.id
            LEFT JOIN domain d
              ON d.id = dwt.domain_id
             AND d.workspace_id = :workspace_id
            WHERE wt.workspace_id = :workspace_id
              AND wt.id IN ({placeholders})
              AND d.id IS NULL
            """
        params = {"workspace_id": workspace_id}
        params.update({f"uid{idx}": int(val) for idx, val in enumerate(table_ids)})
        rows = self._sql.execute_query_mappings(sql, params)
        uncovered = []
        for row in rows:
            table_id = row.get("workspace_table_id")
            if table_id is None:
                continue
            table_id = int(table_id)
            name = row.get("table_name") or name_map.get(table_id) or ""
            uncovered.append(
                {
                    "workspace_table_id": table_id,
                    "table_name": name,
                    "reason": "no domain mapping exists",
                }
            )
        return uncovered


def _normalize_hits(table_hits: Sequence[Mapping[str, Any]]) -> List[_Hit]:
    hits: List[_Hit] = []
    score_map: Dict[int, float] = {}
    name_map: Dict[int, Optional[str]] = {}
    for hit in table_hits or []:
        table_id = hit.get("workspace_table_id") or hit.get("workspaceTableId")
        if table_id is None:
            continue
        try:
            table_id_int = int(table_id)
        except Exception:
            continue
        score = float(hit.get("score") or 0.0)
        if table_id_int not in score_map or score > score_map[table_id_int]:
            score_map[table_id_int] = score
            name_map[table_id_int] = hit.get("table_name") or hit.get("tableName")

    for table_id, score in score_map.items():
        hits.append(_Hit(workspace_table_id=table_id, score=score, table_name=name_map.get(table_id)))
    return hits


def _placeholders(prefix: str, count: int) -> str:
    return ", ".join([f":{prefix}{idx}" for idx in range(count)])
