from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.ports.sql_executor import ForgeQueryPort


class DomainSelectionService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def choose_domain_id(
        self,
        *,
        workspace_id: str,
        mapped_columns: Sequence[Dict[str, Any]],
        required_concept_keys: Sequence[str],
        prompt: str,
        preselected_domain_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        if preselected_domain_id is not None:
            return {
                "domain_id": int(preselected_domain_id),
                "source": "user_selected",
                "threshold_met": True,
                "domains": [],
            }

        required = [str(key or "").strip().upper() for key in required_concept_keys if str(key or "").strip()]
        required = list(dict.fromkeys(required))
        if not required:
            return {
                "domain_id": None,
                "source": "auto",
                "threshold_met": False,
                "domains": [],
            }

        rows = self._sql.execute_query_mappings(
            """
            SELECT
              d.id AS domain_id,
              wt.table_name
            FROM domain d
            JOIN domain_workspace_table dwt
              ON dwt.domain_id = d.id
            JOIN workspace_table wt
              ON wt.id = dwt.workspace_table_id
             AND wt.workspace_id = :workspace_id
             AND wt.exists_in_dbx = 1
            WHERE d.workspace_id = :workspace_id
              AND d.is_active = 1
            ORDER BY d.id ASC
            """,
            {"workspace_id": str(workspace_id)},
        )
        if not rows:
            return {
                "domain_id": None,
                "source": "auto",
                "threshold_met": False,
                "domains": [],
            }

        domain_tables: Dict[int, set[str]] = {}
        for row in rows:
            domain_id = _to_int(row.get("domain_id"))
            table_name = str(row.get("table_name") or "").strip().lower()
            if domain_id is None or table_name == "":
                continue
            domain_tables.setdefault(domain_id, set()).add(table_name)

        by_concept: Dict[str, List[Dict[str, Any]]] = {}
        for row in mapped_columns:
            concept_key = str(row.get("concept_key") or "").strip().upper()
            table_name = str(row.get("table_name") or "").strip().lower()
            if concept_key == "" or table_name == "":
                continue
            by_concept.setdefault(concept_key, []).append(dict(row))

        student_intent = _is_student_prompt(prompt)
        domain_scores: List[Dict[str, Any]] = []
        for domain_id, tables in domain_tables.items():
            covered_concepts: List[str] = []
            best_tables: set[str] = set()
            for concept_key in required:
                candidates = [row for row in by_concept.get(concept_key, []) if str(row.get("table_name") or "").strip().lower() in tables]
                if not candidates:
                    continue
                covered_concepts.append(concept_key)
                best = sorted(
                    candidates,
                    key=lambda row: (
                        -float(row.get("final_score") or row.get("weight") or 0.0),
                        int(row.get("model_column_id") or 0),
                    ),
                )[0]
                best_tables.add(str(best.get("table_name") or "").strip().lower())

            coverage = (len(covered_concepts) / float(len(required))) if required else 0.0
            entity_bonus = 0.1 if student_intent and "dim_student" in tables else 0.0
            table_count = len(best_tables)
            penalty = 0.02 * float(table_count)
            score = coverage + entity_bonus - penalty
            domain_scores.append(
                {
                    "domain_id": domain_id,
                    "coverage": round(coverage, 4),
                    "score": round(score, 4),
                    "entity_bonus": round(entity_bonus, 4),
                    "table_count": table_count,
                    "penalty": round(penalty, 4),
                    "covered_concepts": covered_concepts,
                }
            )

        if not domain_scores:
            return {
                "domain_id": None,
                "source": "auto",
                "threshold_met": False,
                "domains": [],
            }

        best = sorted(
            domain_scores,
            key=lambda row: (
                -float(row.get("score") or 0.0),
                -float(row.get("coverage") or 0.0),
                int(row.get("table_count") or 0),
                int(row.get("domain_id") or 0),
            ),
        )[0]
        threshold_met = float(best.get("coverage") or 0.0) >= 0.60
        return {
            "domain_id": int(best["domain_id"]) if threshold_met else None,
            "source": "auto",
            "threshold_met": threshold_met,
            "domains": domain_scores,
        }


def _is_student_prompt(prompt: str) -> bool:
    text = str(prompt or "").strip().lower()
    if text == "":
        return False
    return re.search(r"\b(student|students|kid|kids|pupil|pupils|learner|learners)\b", text) is not None


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


__all__ = ["DomainSelectionService"]
