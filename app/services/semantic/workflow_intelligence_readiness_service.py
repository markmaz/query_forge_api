from __future__ import annotations

import json
import logging
from typing import Any, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.features.flowforge.reporting.manifest import REPORTING_DOMAINS
from app.features.flowforge.reporting.semantic_sync import FlowForgeSemanticSyncService
from app.ports.sql_executor import ForgeQueryPort

logger = logging.getLogger(__name__)


class WorkflowIntelligenceSemanticReadinessService:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        sync_service: Optional[FlowForgeSemanticSyncService] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._sync_service = sync_service or FlowForgeSemanticSyncService()

    def get_readiness(self, *, workspace_id: str) -> dict[str, Any]:
        ws = str(workspace_id or "").strip()
        sync = self._sync_service.sync_domains(workspace_id=ws, actor_user_id=None, dry_run=True)
        manifest_by_key = {str(domain["domain_key"]): domain for domain in REPORTING_DOMAINS}

        domains: list[dict[str, Any]] = []
        ready_count = 0
        issue_count = 0
        totals = {
            "generated_concept_count": 0,
            "generated_registry_count": 0,
            "concept_column_map_count": 0,
            "semantic_column_map_count": 0,
            "alias_count": 0,
            "metric_count": 0,
            "bound_metric_count": 0,
            "missing_metric_binding_count": 0,
        }

        for sync_domain in list(sync.get("domains") or []):
            domain_key = str(sync_domain.get("domain_key") or "")
            manifest = manifest_by_key.get(domain_key, {})
            payload = sync_domain.get("registration_payload") or {}
            domain_id = _positive_int(payload.get("domain_id"))
            workspace_table_id = _positive_int(payload.get("workspace_table_id"))
            read_model = str(sync_domain.get("read_model") or manifest.get("read_model") or "")
            counts = self._semantic_counts(
                workspace_id=ws,
                domain_key=domain_key,
                read_model=read_model,
                workspace_table_id=workspace_table_id,
            )
            profile_metrics = self._profile_metrics(workspace_id=ws, domain_id=domain_id)
            metric_summary = _metric_summary(manifest=manifest, profile_metrics=profile_metrics)
            issues = [str(issue) for issue in sync_domain.get("registration_issues") or []]
            issues.extend(_semantic_issues(counts=counts, metric_summary=metric_summary, domain_key=domain_key))
            status = "ready" if not issues else "needs_attention"
            if status == "ready":
                ready_count += 1
            else:
                issue_count += 1

            for key in (
                "generated_concept_count",
                "generated_registry_count",
                "concept_column_map_count",
                "semantic_column_map_count",
                "alias_count",
            ):
                totals[key] += int(counts.get(key) or 0)
            totals["metric_count"] += int(metric_summary["metric_count"])
            totals["bound_metric_count"] += int(metric_summary["bound_metric_count"])
            totals["missing_metric_binding_count"] += int(metric_summary["missing_metric_binding_count"])

            domains.append(
                {
                    "domain_key": domain_key,
                    "display_name": str(manifest.get("display_name") or domain_key.replace("_", " ").title()),
                    "read_model": read_model,
                    "registration_status": str(sync_domain.get("registration_status") or ""),
                    "status": status,
                    "issues": issues,
                    "suggested_action": _suggested_action(sync_domain=sync_domain, issues=issues),
                    "queryforge_launch": sync_domain.get("queryforge_launch"),
                    "expected": {
                        "metrics": len(list(manifest.get("metrics") or [])),
                        "dimensions": len(list(manifest.get("dimensions") or [])),
                        "identifiers": len(list(manifest.get("identifiers") or [])),
                        "time_fields": len(list(manifest.get("time_fields") or [])),
                    },
                    "counts": counts,
                    "metric_bindings": metric_summary,
                }
            )

        status = "ready" if issue_count == 0 else "needs_attention"
        return {
            "workspace_id": ws,
            "status": status,
            "summary": {
                "domain_count": len(domains),
                "ready_domain_count": ready_count,
                "issue_domain_count": issue_count,
                **totals,
            },
            "domains": domains,
            "actions": [
                {
                    "id": "sync_workflow_intelligence_semantics",
                    "label": "Sync Workflow Intelligence semantics",
                    "description": "Repairs generated domains, concepts, registry rows, column maps, aliases, and metric bindings.",
                },
                {
                    "id": "rebuild_semantic_indexes",
                    "label": "Rebuild semantic indexes",
                    "description": "Refreshes semantic concept, column/table, and domain vector indexes after the semantic tables are corrected.",
                },
            ],
        }

    def sync_readiness(self, *, workspace_id: str, actor_user_id: str | None) -> dict[str, Any]:
        return self._sync_service.sync_domains(
            workspace_id=str(workspace_id or "").strip(),
            actor_user_id=actor_user_id,
            dry_run=False,
        )

    def _semantic_counts(
        self,
        *,
        workspace_id: str,
        domain_key: str,
        read_model: str,
        workspace_table_id: int | None,
    ) -> dict[str, int]:
        prefix = f"{domain_key.upper()}__%"
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              (SELECT COUNT(*)
                 FROM semantic_concept sc
                WHERE sc.concept_key LIKE :concept_prefix
                  AND sc.`status` = 'active') AS generated_concept_count,
              (SELECT COUNT(*)
                 FROM semantic_registry sr
                WHERE sr.concept_key LIKE :concept_prefix) AS generated_registry_count,
              (SELECT COUNT(*)
                 FROM workspace_column_semantic_concept_map m
                 JOIN semantic_concept sc
                   ON sc.id = m.semantic_concept_id
                 JOIN workspace_column wc
                   ON wc.id = m.workspace_column_id
                 JOIN workspace_table wt
                   ON wt.id = wc.workspace_table_id
                WHERE sc.concept_key LIKE :concept_prefix
                  AND wt.workspace_id = :workspace_id
                  AND (:workspace_table_id IS NULL OR wt.id = :workspace_table_id)) AS concept_column_map_count,
              (SELECT COUNT(*)
                 FROM semantic_column_map scm
                 JOIN semantic_registry sr
                   ON sr.id = scm.semantic_registry_id
                WHERE sr.concept_key LIKE :concept_prefix
                  AND scm.workspace_id = :workspace_id
                  AND (:read_model = '' OR scm.table_name = :read_model)) AS semantic_column_map_count,
              (SELECT COUNT(*)
                 FROM semantic_concept_alias a
                WHERE a.concept_key LIKE :concept_prefix) AS alias_count
            """,
            {
                "workspace_id": workspace_id,
                "workspace_table_id": workspace_table_id,
                "read_model": read_model,
                "concept_prefix": prefix,
            },
        )
        row = dict(rows[0]) if rows else {}
        return {
            "generated_concept_count": int(row.get("generated_concept_count") or 0),
            "generated_registry_count": int(row.get("generated_registry_count") or 0),
            "concept_column_map_count": int(row.get("concept_column_map_count") or 0),
            "semantic_column_map_count": int(row.get("semantic_column_map_count") or 0),
            "alias_count": int(row.get("alias_count") or 0),
        }

    def _profile_metrics(self, *, workspace_id: str, domain_id: int | None) -> list[dict[str, Any]]:
        if domain_id is None:
            return []
        rows = self._sql.execute_query_mappings(
            """
            SELECT metrics
            FROM domain_profile
            WHERE workspace_id = :workspace_id
              AND domain_id = :domain_id
            LIMIT 1
            """,
            {"workspace_id": workspace_id, "domain_id": domain_id},
        )
        if not rows:
            return []
        raw = (rows[0] or {}).get("metrics")
        if isinstance(raw, list):
            return [item for item in raw if isinstance(item, dict)]
        try:
            parsed = json.loads(str(raw or "[]"))
        except (TypeError, ValueError):
            logger.warning("Workflow Intelligence domain_profile metrics JSON was invalid domain_id=%s", domain_id)
            return []
        return [item for item in parsed if isinstance(item, dict)]


def _metric_summary(*, manifest: dict[str, Any], profile_metrics: list[dict[str, Any]]) -> dict[str, Any]:
    expected_keys = [
        str(item.get("key") or item.get("metric_key") or "").strip()
        for item in list(manifest.get("metrics") or [])
        if isinstance(item, dict)
    ]
    expected_keys = [key for key in expected_keys if key]
    by_key = {
        str(item.get("metric_key") or item.get("key") or "").strip(): item
        for item in profile_metrics
        if str(item.get("metric_key") or item.get("key") or "").strip()
    }
    missing = [key for key in expected_keys if key not in by_key]
    unbound = [
        key
        for key in expected_keys
        if key in by_key and not (by_key[key].get("sql_metric") or by_key[key].get("column_key"))
    ]
    bound = [key for key in expected_keys if key in by_key and key not in unbound]
    return {
        "metric_count": len(expected_keys),
        "profile_metric_count": len(by_key),
        "bound_metric_count": len(bound),
        "missing_metric_count": len(missing),
        "missing_metric_binding_count": len(unbound),
        "missing_metrics": missing,
        "unbound_metrics": unbound,
        "bound_metrics": bound,
    }


def _semantic_issues(*, counts: dict[str, int], metric_summary: dict[str, Any], domain_key: str) -> list[str]:
    issues: list[str] = []
    if counts["generated_concept_count"] <= 0:
        issues.append(f"{domain_key} has no generated semantic concepts.")
    if counts["generated_registry_count"] <= 0:
        issues.append(f"{domain_key} has no generated semantic registry rows.")
    if counts["semantic_column_map_count"] <= 0:
        issues.append(f"{domain_key} has no semantic column-map rows.")
    if int(metric_summary["metric_count"]) > 0 and int(metric_summary["profile_metric_count"]) <= 0:
        issues.append(f"{domain_key} has no generated domain-profile metrics.")
    if int(metric_summary["missing_metric_count"]) > 0:
        issues.append(f"{domain_key} is missing generated metrics: {', '.join(metric_summary['missing_metrics'])}.")
    if int(metric_summary["missing_metric_binding_count"]) > 0:
        issues.append(f"{domain_key} has unbound generated metrics: {', '.join(metric_summary['unbound_metrics'])}.")
    return issues


def _suggested_action(*, sync_domain: dict[str, Any], issues: list[str]) -> str:
    status = str(sync_domain.get("registration_status") or "")
    if status in {"read_model_missing", "sensitive_mismatch", "manifest_invalid"}:
        return "Apply the latest Workflow Intelligence read-model migrations, then run semantic sync."
    if status in {"registration_missing", "table_mapping_missing", "columns_missing"}:
        return "Run Workflow Intelligence semantic sync for this workspace."
    if any("unbound generated metrics" in issue for issue in issues):
        return "Apply the latest Workflow Intelligence metric-flag read-model migration, then run semantic sync and rebuild indexes."
    if any("generated semantic" in issue for issue in issues):
        return "Run Workflow Intelligence semantic sync, then rebuild semantic indexes."
    if any("column-map" in issue for issue in issues):
        return "Run semantic sync and verify generated read-model columns are active."
    return "No action needed."


def _positive_int(value: Any) -> int | None:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return None
    return coerced if coerced > 0 else None
