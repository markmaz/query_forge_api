from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.features.flowforge.reporting.manifest import REPORTING_DOMAINS, validate_reporting_manifest
from app.features.flowforge.reporting.read_model_audit import audit_reporting_read_model_sql
from app.features.flowforge.reporting.semantic_metadata import (
    domain_profile_params,
    load_workspace_column_ids,
    semantic_column_metadata,
    upsert_generated_semantic_metadata,
)
from app.ports.sql_executor import ForgeQueryPort

_MIGRATION_PATHS = (
    Path("migrations/20260505_flowforge_reporting_read_models.sql"),
    Path("migrations/20260506_flowforge_data_movement_reporting_read_models.sql"),
    Path("migrations/20260510_flowforge_workflow_intelligence_read_models.sql"),
    Path("migrations/20260512_flowforge_workflow_intelligence_metric_flags.sql"),
)


class FlowForgeSemanticDomainRegistry(Protocol):
    def upsert_generated_domain(
        self,
        *,
        workspace_id: str,
        domain: dict[str, Any],
        actor_user_id: str | None,
    ) -> dict[str, Any]:
        ...


class QueryForgeFlowForgeSemanticDomainRegistry:
    def __init__(self, *, sql: ForgeQueryPort | None = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def get_generated_domain_status(self, *, workspace_id: str, domain: dict[str, Any]) -> dict[str, Any]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              d.id AS domain_id,
              wt.id AS workspace_table_id,
              COUNT(wc.id) AS column_count
            FROM domain d
            LEFT JOIN domain_workspace_table dwt
              ON dwt.domain_id = d.id
            LEFT JOIN workspace_table wt
              ON wt.id = dwt.workspace_table_id
             AND wt.workspace_id = d.workspace_id
             AND wt.full_name = CONCAT(DATABASE(), '.', :read_model)
             AND wt.exists_in_dbx = 1
            LEFT JOIN workspace_column wc
              ON wc.workspace_table_id = wt.id
             AND wc.is_active = 1
            WHERE d.workspace_id = :workspace_id
              AND d.name = :display_name
              AND d.is_active = 1
            GROUP BY d.id, wt.id
            LIMIT 1
            """,
            {
                "workspace_id": workspace_id,
                "display_name": domain["display_name"],
                "read_model": domain["read_model"],
            },
        )
        if not rows:
            return {
                "registration_status": "registration_missing",
                "registration_issues": ["QueryForge generated domain is not registered."],
            }

        row = dict(rows[0])
        if row.get("workspace_table_id") is None:
            return {
                "registration_status": "table_mapping_missing",
                "domain_id": int(row.get("domain_id") or 0) or None,
                "registration_issues": ["QueryForge generated domain is missing its read-model table mapping."],
            }
        if int(row.get("column_count") or 0) <= 0:
            return {
                "registration_status": "columns_missing",
                "domain_id": int(row.get("domain_id") or 0) or None,
                "registration_issues": ["QueryForge generated domain has no active read-model columns."],
            }
        return {
            "registration_status": "registered",
            "registration_issues": [],
            "domain_id": int(row.get("domain_id") or 0) or None,
            "workspace_table_id": int(row.get("workspace_table_id") or 0) or None,
            "column_count": int(row.get("column_count") or 0),
        }

    def upsert_generated_domain(
        self,
        *,
        workspace_id: str,
        domain: dict[str, Any],
        actor_user_id: str | None,
    ) -> dict[str, Any]:
        columns = self._load_read_model_columns(read_model=str(domain["read_model"]))
        if not columns:
            raise RuntimeError(f"Read model {domain['read_model']} does not exist or has no columns.")

        full_name = self._read_model_full_name(read_model=str(domain["read_model"]))
        domain_id: int | None = None
        workspace_table_id: int | None = None
        with self._sql.transaction() as tx:
            tx.execute_write(
                """
                INSERT INTO workspace (id, display_name)
                VALUES (:workspace_id, :display_name)
                ON DUPLICATE KEY UPDATE id = id
                """,
                {"workspace_id": workspace_id, "display_name": None},
            )
            tx.execute_write(
                """
                INSERT INTO domain (
                  workspace_id,
                  name,
                  kind,
                  description,
                  column_name_policy,
                  is_active,
                  created_at,
                  updated_at
                )
                VALUES (
                  :workspace_id,
                  :name,
                  :kind,
                  :description,
                  'DEDUP_PRIMARY_FIRST',
                  1,
                  CURRENT_TIMESTAMP,
                  CURRENT_TIMESTAMP
                )
                ON DUPLICATE KEY UPDATE
                  kind = VALUES(kind),
                  description = VALUES(description),
                  column_name_policy = VALUES(column_name_policy),
                  is_active = 1,
                  updated_at = CURRENT_TIMESTAMP
                """,
                {
                    "workspace_id": workspace_id,
                    "name": domain["display_name"],
                    "kind": domain["domain_group"],
                    "description": domain["description"],
                },
            )
            domain_rows = tx.execute_query_mappings(
                """
                SELECT id
                FROM domain
                WHERE workspace_id = :workspace_id
                  AND name = :name
                LIMIT 1
                """,
                {"workspace_id": workspace_id, "name": domain["display_name"]},
            )
            if not domain_rows:
                raise RuntimeError(f"Failed to upsert domain {domain['domain_key']}.")
            domain_id = int(domain_rows[0]["id"])

            tx.execute_write(
                """
                INSERT INTO workspace_table (
                  workspace_id,
                  catalog_name,
                  schema_name,
                  table_name,
                  full_name,
                  source_table_name,
                  variant_code,
                  is_qe,
                  exists_in_dbx,
                  last_seen_at,
                  created_at,
                  updated_at,
                  description,
                  origin,
                  is_missing_in_source,
                  metadata_synced_at,
                  metadata_updated_at
                )
                VALUES (
                  :workspace_id,
                  DATABASE(),
                  DATABASE(),
                  :read_model,
                  :full_name,
                  :source_table_name,
                  :variant_code,
                  0,
                  1,
                  CURRENT_TIMESTAMP,
                  CURRENT_TIMESTAMP,
                  CURRENT_TIMESTAMP,
                  :description,
                  'FLOWFORGE',
                  0,
                  CURRENT_TIMESTAMP,
                  CURRENT_TIMESTAMP
                )
                ON DUPLICATE KEY UPDATE
                  table_name = VALUES(table_name),
                  source_table_name = VALUES(source_table_name),
                  variant_code = VALUES(variant_code),
                  description = VALUES(description),
                  origin = 'FLOWFORGE',
                  exists_in_dbx = 1,
                  is_missing_in_source = 0,
                  last_seen_at = CURRENT_TIMESTAMP,
                  metadata_synced_at = CURRENT_TIMESTAMP,
                  metadata_updated_at = CURRENT_TIMESTAMP,
                  updated_at = CURRENT_TIMESTAMP
                """,
                {
                    "workspace_id": workspace_id,
                    "read_model": domain["read_model"],
                    "full_name": full_name,
                    "source_table_name": domain["display_name"],
                    "variant_code": domain["domain_key"],
                    "description": domain["description"],
                },
            )
            table_rows = tx.execute_query_mappings(
                """
                SELECT id
                FROM workspace_table
                WHERE workspace_id = :workspace_id
                  AND full_name = :full_name
                LIMIT 1
                """,
                {"workspace_id": workspace_id, "full_name": full_name},
            )
            if not table_rows:
                raise RuntimeError(f"Failed to upsert workspace table for {domain['domain_key']}.")
            workspace_table_id = int(table_rows[0]["id"])

            for column in columns:
                semantic = semantic_column_metadata(domain=domain, column=column)
                tx.execute_write(
                    """
                    INSERT INTO workspace_column (
                      workspace_table_id,
                      column_name,
                      data_type,
                      nullable,
                      ordinal_position,
                      exists_in_dbx,
                      last_seen_at,
                      created_at,
                      updated_at,
                      description,
                      is_active,
                      origin,
                      is_missing_in_source,
                      semantic_type,
                      semantic_entity,
                      semantic_sub_type,
                      semantic_source,
                      semantic_confidence,
                      semantic_concept_key,
                      semantic_assigned_at,
                      metadata_updated_at
                    )
                    VALUES (
                      :workspace_table_id,
                      :column_name,
                      :data_type,
                      :nullable,
                      :ordinal_position,
                      1,
                      CURRENT_TIMESTAMP,
                      CURRENT_TIMESTAMP,
                      CURRENT_TIMESTAMP,
                      :description,
                      1,
                      'FLOWFORGE',
                      0,
                      :semantic_type,
                      :semantic_entity,
                      :semantic_sub_type,
                      'system',
                      1.0,
                      :semantic_concept_key,
                      CURRENT_TIMESTAMP,
                      CURRENT_TIMESTAMP
                    )
                    ON DUPLICATE KEY UPDATE
                      data_type = VALUES(data_type),
                      nullable = VALUES(nullable),
                      ordinal_position = VALUES(ordinal_position),
                      exists_in_dbx = 1,
                      last_seen_at = CURRENT_TIMESTAMP,
                      updated_at = CURRENT_TIMESTAMP,
                      description = VALUES(description),
                      is_active = 1,
                      origin = 'FLOWFORGE',
                      is_missing_in_source = 0,
                      semantic_type = VALUES(semantic_type),
                      semantic_entity = VALUES(semantic_entity),
                      semantic_sub_type = VALUES(semantic_sub_type),
                      semantic_source = 'system',
                      semantic_confidence = 1.0,
                      semantic_concept_key = VALUES(semantic_concept_key),
                      semantic_assigned_at = CURRENT_TIMESTAMP,
                      metadata_updated_at = CURRENT_TIMESTAMP
                    """,
                    {
                        "workspace_table_id": workspace_table_id,
                        "column_name": column["column_name"],
                        "data_type": column["data_type"],
                        "nullable": 1 if column["nullable"] else 0,
                        "ordinal_position": column["ordinal_position"],
                        "description": semantic["description"],
                        "semantic_type": semantic["semantic_type"],
                        "semantic_entity": semantic["semantic_entity"],
                        "semantic_sub_type": semantic["semantic_sub_type"],
                        "semantic_concept_key": semantic["semantic_concept_key"],
                    },
            )

            _deactivate_missing_columns(tx, workspace_table_id=workspace_table_id, columns=columns)
            semantic_counts = upsert_generated_semantic_metadata(
                tx,
                workspace_id=workspace_id,
                domain=domain,
                workspace_table_id=workspace_table_id,
                columns=columns,
            )
            tx.execute_write(
                "UPDATE domain_workspace_table SET is_primary = 0 WHERE domain_id = :domain_id",
                {"domain_id": domain_id},
            )
            tx.execute_write(
                """
                INSERT INTO domain_workspace_table (
                  domain_id,
                  workspace_table_id,
                  relation_kind,
                  is_primary,
                  sort_order,
                  role,
                  table_alias,
                  filter_mode,
                  cardinality,
                  created_at
                )
                VALUES (
                  :domain_id,
                  :workspace_table_id,
                  'JOIN',
                  1,
                  0,
                  'primary',
                  :table_alias,
                  'AUTO',
                  'ONE',
                  CURRENT_TIMESTAMP
                )
                ON DUPLICATE KEY UPDATE
                  relation_kind = 'JOIN',
                  is_primary = 1,
                  sort_order = 0,
                  role = 'primary',
                  table_alias = VALUES(table_alias),
                  filter_mode = 'AUTO',
                  cardinality = 'ONE'
                """,
                {
                    "domain_id": domain_id,
                    "workspace_table_id": workspace_table_id,
                    "table_alias": _table_alias(domain),
                },
            )
            tx.execute_write(
                """
                INSERT INTO domain_profile (
                  workspace_id,
                  domain_id,
                  summary,
                  keywords,
                  entities,
                  metrics,
                  attributes,
                  synonyms,
                  acronyms,
                  notes,
                  embedding_text,
                  content_hash,
                  created_at,
                  updated_at
                )
                VALUES (
                  :workspace_id,
                  :domain_id,
                  :summary,
                  :keywords,
                  :entities,
                  :metrics,
                  :attributes,
                  :synonyms,
                  :acronyms,
                  :notes,
                  :embedding_text,
                  :content_hash,
                  CURRENT_TIMESTAMP,
                  CURRENT_TIMESTAMP
                )
                ON DUPLICATE KEY UPDATE
                  summary = VALUES(summary),
                  keywords = VALUES(keywords),
                  entities = VALUES(entities),
                  metrics = VALUES(metrics),
                  attributes = VALUES(attributes),
                  synonyms = VALUES(synonyms),
                  acronyms = VALUES(acronyms),
                  notes = VALUES(notes),
                  embedding_text = VALUES(embedding_text),
                  content_hash = VALUES(content_hash),
                  updated_at = CURRENT_TIMESTAMP
                """,
                domain_profile_params(
                    workspace_id=workspace_id,
                    domain_id=domain_id,
                    domain=domain,
                    workspace_table_id=workspace_table_id,
                    columns=columns,
                    column_id_by_name=load_workspace_column_ids(tx, workspace_table_id=workspace_table_id),
                ),
            )
            tx.execute_write(
                """
                INSERT INTO user_domain_mapping (user_id, domain_id, can_read, can_edit, created_at)
                SELECT
                  wm.user_id,
                  :domain_id,
                  1,
                  CASE WHEN wm.role IN ('owner', 'admin') THEN 1 ELSE 0 END,
                  CURRENT_TIMESTAMP
                FROM workspace_membership wm
                WHERE wm.workspace_id = :workspace_id
                  AND wm.is_active = 1
                ON DUPLICATE KEY UPDATE
                  can_read = 1,
                  can_edit = GREATEST(can_edit, VALUES(can_edit))
                """,
                {"workspace_id": workspace_id, "domain_id": domain_id},
            )
            if actor_user_id:
                tx.execute_write(
                    """
                    INSERT INTO user_domain_mapping (user_id, domain_id, can_read, can_edit, created_at)
                    VALUES (:actor_user_id, :domain_id, 1, 1, CURRENT_TIMESTAMP)
                    ON DUPLICATE KEY UPDATE can_read = 1, can_edit = 1
                    """,
                    {"actor_user_id": actor_user_id, "domain_id": domain_id},
                )

        return {
            "workspace_id": workspace_id,
            "domain_key": domain["domain_key"],
            "domain_id": domain_id,
            "workspace_table_id": workspace_table_id,
            "read_model": domain["read_model"],
            "column_count": len(columns),
            "actor_user_id": actor_user_id,
            "domain_source": domain["domain_source"],
            "domain_group": domain["domain_group"],
            **semantic_counts,
        }

    def _read_model_full_name(self, *, read_model: str) -> str:
        rows = self._sql.execute_query_mappings("SELECT DATABASE() AS database_name", {})
        database_name = str((rows[0] if rows else {}).get("database_name") or "").strip()
        if not database_name:
            raise RuntimeError("Database name could not be resolved for FlowForge read model registration.")
        return f"{database_name}.{read_model}"

    def _load_read_model_columns(self, *, read_model: str) -> list[dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              COLUMN_NAME AS column_name,
              DATA_TYPE AS data_type,
              IS_NULLABLE AS is_nullable,
              ORDINAL_POSITION AS ordinal_position
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = :read_model
            ORDER BY ORDINAL_POSITION ASC
            """,
            {"read_model": read_model},
        )
        return [
            {
                "column_name": str(row.get("column_name") or "").strip(),
                "data_type": str(row.get("data_type") or "varchar").strip() or "varchar",
                "nullable": str(row.get("is_nullable") or "YES").upper() == "YES",
                "ordinal_position": int(row.get("ordinal_position") or 0),
            }
            for row in rows
            if str(row.get("column_name") or "").strip()
        ]


class NoopFlowForgeSemanticDomainRegistry:
    def upsert_generated_domain(
        self,
        *,
        workspace_id: str,
        domain: dict[str, Any],
        actor_user_id: str | None,
    ) -> dict[str, Any]:
        return {
            "workspace_id": workspace_id,
            "domain_key": domain["domain_key"],
            "domain_source": domain["domain_source"],
            "domain_group": domain["domain_group"],
            "actor_user_id": actor_user_id,
        }


class FlowForgeSemanticSyncService:
    def __init__(
        self,
        *,
        registry: FlowForgeSemanticDomainRegistry | None = None,
        migration_sql: str | None = None,
    ) -> None:
        self._registry = registry or QueryForgeFlowForgeSemanticDomainRegistry()
        self._migration_sql = migration_sql

    def domain_status_index(self, *, workspace_id: str) -> dict[str, dict[str, Any]]:
        result = self.sync_domains(workspace_id=workspace_id, actor_user_id=None, dry_run=True)
        return {str(domain["domain_key"]): domain for domain in result["domains"]}

    def sync_domains(
        self,
        *,
        workspace_id: str,
        actor_user_id: str | None,
        dry_run: bool,
    ) -> dict[str, Any]:
        manifest_errors = validate_reporting_manifest()
        read_model_errors = audit_reporting_read_model_sql(self._load_migration_sql())
        errors_by_domain = _group_errors_by_domain([*manifest_errors, *read_model_errors])
        domain_results: list[dict[str, Any]] = []
        registered_count = 0

        for domain in REPORTING_DOMAINS:
            domain_key = str(domain["domain_key"])
            issues = errors_by_domain.get(domain_key, [])
            status = _status_for_issues(issues, dry_run=dry_run)
            if dry_run and not issues and hasattr(self._registry, "get_generated_domain_status"):
                registry_status = self._registry.get_generated_domain_status(
                    workspace_id=workspace_id,
                    domain=domain,
                )
                status = str(registry_status.get("registration_status") or status)
                registration_payload = dict(registry_status)
                registry_issues = list(registry_status.get("registration_issues") or [])
                if registry_issues:
                    issues.extend(registry_issues)
            else:
                registration_payload = None
            if not dry_run and not issues:
                registration_payload = self._registry.upsert_generated_domain(
                    workspace_id=workspace_id,
                    domain=domain,
                    actor_user_id=actor_user_id,
                )
                registered_count += 1
            domain_results.append(
                {
                    "workspace_id": workspace_id,
                    "domain_key": domain_key,
                    "read_model": domain["read_model"],
                    "registration_status": status,
                    "registration_issues": issues,
                    "queryforge_launch": queryforge_launch_metadata(
                        domain,
                        domain_id=_coerce_positive_int((registration_payload or {}).get("domain_id")),
                    ),
                    "registration_payload": registration_payload,
                }
            )

        overall_status = "ok" if not any(domain["registration_issues"] for domain in domain_results) else "issues_found"
        return {
            "workspace_id": workspace_id,
            "dry_run": dry_run,
            "status": overall_status,
            "domain_count": len(REPORTING_DOMAINS),
            "registered_count": registered_count,
            "domains": domain_results,
        }

    def _load_migration_sql(self) -> str:
        if self._migration_sql is not None:
            return self._migration_sql
        parts: list[str] = []
        for path in _MIGRATION_PATHS:
            if path.exists():
                parts.append(path.read_text(encoding="utf-8"))
        return "\n".join(parts)


def queryforge_launch_metadata(domain: dict[str, Any], *, domain_id: int | None = None) -> dict[str, Any]:
    prompts = list(domain.get("query_studio_prompts") or [])
    payload = {
        "source": "flowforge",
        "domain_key": domain["domain_key"],
        "read_model": domain["read_model"],
        "domain_group": domain["domain_group"],
        "domain_source": domain["domain_source"],
        "default_filters": list(domain.get("default_filters") or []),
        "starter_prompt": prompts[0] if prompts else None,
    }
    if domain_id is not None:
        payload["domain_id"] = domain_id
    return payload


def _coerce_positive_int(value: Any) -> int | None:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return None
    return coerced if coerced > 0 else None


def _group_errors_by_domain(errors: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for error in errors:
        domain_key, _, message = error.partition(": ")
        grouped.setdefault(domain_key or "<unknown>", []).append(message or error)
    return grouped


def _status_for_issues(issues: list[str], *, dry_run: bool) -> str:
    if not issues:
        return "validated" if dry_run else "registered"
    if any("missing from migration SQL" in issue for issue in issues):
        return "read_model_missing"
    if any("sensitive field" in issue for issue in issues):
        return "sensitive_mismatch"
    return "manifest_invalid"


def _deactivate_missing_columns(tx: Any, *, workspace_table_id: int, columns: list[dict[str, Any]]) -> None:
    keep = [str(column["column_name"]) for column in columns]
    if not keep:
        return
    placeholders = ", ".join(f":c{i}" for i in range(len(keep)))
    params = {"workspace_table_id": int(workspace_table_id), **{f"c{i}": name for i, name in enumerate(keep)}}
    tx.execute_write(
        f"""
        UPDATE workspace_column
        SET is_active = 0,
            is_missing_in_source = 1,
            metadata_updated_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE workspace_table_id = :workspace_table_id
          AND origin = 'FLOWFORGE'
          AND column_name NOT IN ({placeholders})
        """,
        params,
    )


def _table_alias(domain: dict[str, Any]) -> str:
    raw = str(domain.get("domain_key") or "flowforge").replace("flowforge_", "ff_", 1)
    alias = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in raw.lower())
    return alias[:64] or "flowforge"
