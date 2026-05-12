from __future__ import annotations

import hashlib
import json
from typing import Any


def semantic_column_metadata(*, domain: dict[str, Any], column: dict[str, Any]) -> dict[str, str]:
    column_name = str(column["column_name"])
    metric_keys = _field_keys(domain.get("metrics"))
    dimension_keys = _field_keys(domain.get("dimensions"))
    identifiers = {str(item) for item in domain.get("identifiers") or []}
    time_fields = {str(item) for item in domain.get("time_fields") or []}
    if column_name in time_fields or column_name.endswith("_at") or column_name.endswith("_date"):
        semantic_type = "time"
    elif column_name in identifiers or column_name == domain.get("workspace_scope_field") or column_name.endswith("_id"):
        semantic_type = "identifier"
    elif column_name in metric_keys or column_name.endswith("_count") or column_name.endswith("_seconds"):
        semantic_type = "metric"
    elif column_name.startswith("is_") or column_name.endswith("_flag") or column_name in {"selected", "included", "excluded"}:
        semantic_type = "flag"
    else:
        semantic_type = "attribute" if column_name in dimension_keys else "other"

    label = _field_label(domain.get("metrics"), column_name)
    if label == column_name.replace("_", " ").title():
        label = _field_label(domain.get("dimensions"), column_name)
    return {
        "semantic_type": semantic_type,
        "semantic_entity": str(domain["domain_key"])[:100],
        "semantic_sub_type": str(domain["domain_group"])[:200],
        "semantic_concept_key": f"{str(domain['domain_key']).upper()}__{column_name.upper()}"[:128],
        "description": label,
    }


def load_workspace_column_ids(tx: Any, *, workspace_table_id: int) -> dict[str, int]:
    rows = tx.execute_query_mappings(
        """
        SELECT id, column_name
        FROM workspace_column
        WHERE workspace_table_id = :workspace_table_id
          AND is_active = 1
        """,
        {"workspace_table_id": int(workspace_table_id)},
    )
    out: dict[str, int] = {}
    for row in rows:
        name = str(row.get("column_name") or "").strip()
        if name and row.get("id") is not None:
            out[name] = int(row["id"])
    return out


def upsert_generated_semantic_metadata(
    tx: Any,
    *,
    workspace_id: str,
    domain: dict[str, Any],
    workspace_table_id: int,
    columns: list[dict[str, Any]],
) -> dict[str, int]:
    column_id_by_name = load_workspace_column_ids(tx, workspace_table_id=workspace_table_id)
    concept_count = 0
    alias_count = 0
    concept_map_count = 0
    registry_count = 0
    registry_map_count = 0

    for column in columns:
        column_name = str(column.get("column_name") or "").strip()
        workspace_column_id = column_id_by_name.get(column_name)
        if not column_name or workspace_column_id is None:
            continue
        semantic = semantic_column_metadata(domain=domain, column=column)
        concept_key = str(semantic["semantic_concept_key"]).upper()
        semantic_type = str(semantic["semantic_type"]).lower()
        is_metric = semantic_type == "metric"
        is_identifier = semantic_type == "identifier"
        group_by_allowed = semantic_type in {"attribute", "time", "identifier", "flag"}
        aggregation_allowed = is_metric
        display_priority = _semantic_display_priority(semantic_type)
        concept_payload = {
            "concept_key": concept_key,
            "name": semantic["description"],
            "description": _concept_description(domain=domain, column_name=column_name, semantic=semantic),
            "semantic_type": semantic_type,
            "sub_type": semantic["semantic_sub_type"],
            "entity": semantic["semantic_entity"],
            "granularity_rank": 0,
            "filter_allowed": 1,
            "group_by_allowed": 1 if group_by_allowed else 0,
            "aggregation_allowed": 1 if aggregation_allowed else 0,
            "is_identifier": 1 if is_identifier else 0,
            "is_metric": 1 if is_metric else 0,
            "display_priority": display_priority,
            "sensitive": 0,
            "status": "active",
        }
        tx.execute_write(
            """
            INSERT INTO semantic_concept (
              concept_key, name, description, semantic_type, sub_type, entity,
              granularity_rank, filter_allowed, group_by_allowed, aggregation_allowed,
              is_identifier, is_metric, display_priority, `sensitive`, `status`
            ) VALUES (
              :concept_key, :name, :description, :semantic_type, :sub_type, :entity,
              :granularity_rank, :filter_allowed, :group_by_allowed, :aggregation_allowed,
              :is_identifier, :is_metric, :display_priority, :sensitive, :status
            )
            ON DUPLICATE KEY UPDATE
              name = VALUES(name),
              description = VALUES(description),
              semantic_type = VALUES(semantic_type),
              sub_type = VALUES(sub_type),
              entity = VALUES(entity),
              granularity_rank = VALUES(granularity_rank),
              filter_allowed = VALUES(filter_allowed),
              group_by_allowed = VALUES(group_by_allowed),
              aggregation_allowed = VALUES(aggregation_allowed),
              is_identifier = VALUES(is_identifier),
              is_metric = VALUES(is_metric),
              display_priority = VALUES(display_priority),
              `sensitive` = VALUES(`sensitive`),
              `status` = VALUES(`status`),
              updated_at = CURRENT_TIMESTAMP
            """,
            concept_payload,
        )
        concept_id = _lookup_id(tx, table_name="semantic_concept", concept_key=concept_key)
        if concept_id is None:
            continue
        concept_count += 1

        tx.execute_write(
            """
            INSERT INTO workspace_column_semantic_concept_map (
              semantic_concept_id, workspace_column_id, relationship_kind, weight
            ) VALUES (
              :semantic_concept_id, :workspace_column_id, 'primary', :weight
            )
            ON DUPLICATE KEY UPDATE
              weight = VALUES(weight)
            """,
            {"semantic_concept_id": concept_id, "workspace_column_id": workspace_column_id, "weight": 1.0},
        )
        concept_map_count += 1

        tx.execute_write(
            """
            INSERT INTO semantic_registry (
              concept_key, semantic_type, sub_type, entity, description,
              granularity_rank, filter_allowed, group_by_allowed, aggregation_allowed,
              is_identifier, is_metric, display_priority, `sensitive`
            ) VALUES (
              :concept_key, :semantic_type, :sub_type, :entity, :description,
              :granularity_rank, :filter_allowed, :group_by_allowed, :aggregation_allowed,
              :is_identifier, :is_metric, :display_priority, :sensitive
            )
            ON DUPLICATE KEY UPDATE
              semantic_type = VALUES(semantic_type),
              sub_type = VALUES(sub_type),
              entity = VALUES(entity),
              description = VALUES(description),
              granularity_rank = VALUES(granularity_rank),
              filter_allowed = VALUES(filter_allowed),
              group_by_allowed = VALUES(group_by_allowed),
              aggregation_allowed = VALUES(aggregation_allowed),
              is_identifier = VALUES(is_identifier),
              is_metric = VALUES(is_metric),
              display_priority = VALUES(display_priority),
              `sensitive` = VALUES(`sensitive`),
              updated_at = CURRENT_TIMESTAMP
            """,
            {key: value for key, value in concept_payload.items() if key != "name" and key != "status"},
        )
        registry_id = _lookup_id(tx, table_name="semantic_registry", concept_key=concept_key)
        if registry_id is not None:
            registry_count += 1
            tx.execute_write(
                """
                INSERT INTO semantic_column_map (
                  semantic_registry_id,
                  workspace_id,
                  workspace_column_id,
                  table_name,
                  column_name,
                  priority_rank,
                  confidence_score
                ) VALUES (
                  :semantic_registry_id,
                  :workspace_id,
                  :workspace_column_id,
                  :table_name,
                  :column_name,
                  :priority_rank,
                  :confidence_score
                )
                ON DUPLICATE KEY UPDATE
                  workspace_column_id = VALUES(workspace_column_id),
                  table_name = VALUES(table_name),
                  column_name = VALUES(column_name),
                  priority_rank = VALUES(priority_rank),
                  confidence_score = VALUES(confidence_score)
                """,
                {
                    "semantic_registry_id": registry_id,
                    "workspace_id": workspace_id,
                    "workspace_column_id": workspace_column_id,
                    "table_name": domain["read_model"],
                    "column_name": column_name,
                    "priority_rank": display_priority,
                    "confidence_score": 1.0,
                },
            )
            registry_map_count += 1

        for alias in _semantic_aliases_for_column(domain=domain, column_name=column_name, semantic=semantic):
            tx.execute_write(
                """
                INSERT INTO semantic_concept_alias (
                  alias_key, concept_key, match_kind, weight
                ) VALUES (
                  :alias_key, :concept_key, :match_kind, :weight
                )
                ON DUPLICATE KEY UPDATE
                  weight = GREATEST(weight, VALUES(weight))
                """,
                {
                    "alias_key": alias["alias_key"],
                    "concept_key": concept_key,
                    "match_kind": alias["match_kind"],
                    "weight": alias["weight"],
                },
            )
            alias_count += 1

    return {
        "semantic_concept_count": concept_count,
        "semantic_alias_count": alias_count,
        "semantic_concept_map_count": concept_map_count,
        "semantic_registry_count": registry_count,
        "semantic_column_map_count": registry_map_count,
    }


def domain_profile_params(
    *,
    workspace_id: str,
    domain_id: int,
    domain: dict[str, Any],
    workspace_table_id: int | None = None,
    columns: list[dict[str, Any]] | None = None,
    column_id_by_name: dict[str, int] | None = None,
) -> dict[str, Any]:
    synonyms = [item for item in list(domain.get("synonyms") or []) if isinstance(item, dict)]
    synonym_terms = _synonym_text_terms(synonyms)
    keywords = [
        domain["domain_group"],
        domain["domain_source"],
        domain["read_model"],
        domain["queryforge_visibility"],
        *synonym_terms,
    ]
    entities = [{"key": key, "label": key.replace("_", " ").title()} for key in domain.get("identifiers") or []]
    metrics = [
        _domain_profile_metric_config(
            item=item,
            domain=domain,
            workspace_table_id=workspace_table_id,
            columns=columns or [],
            column_id_by_name=column_id_by_name or {},
        )
        for item in list(domain.get("metrics") or [])
        if isinstance(item, dict)
    ]
    attributes = list(domain.get("dimensions") or [])
    notes = (
        f"System-managed FlowForge Workflow Intelligence domain. "
        f"domain_key={domain['domain_key']}; read_model={domain['read_model']}; "
        f"visibility={domain['queryforge_visibility']}. Do not edit generated manifest fields directly."
    )
    embedding_text = "\n".join(
        [
            f"Domain: {domain['display_name']}",
            f"Description: {domain['description']}",
            f"Read model: {domain['read_model']}",
            f"Metrics: {', '.join(str(item.get('label') or item.get('key')) for item in domain.get('metrics') or [])}",
            f"Dimensions: {', '.join(str(item.get('label') or item.get('key')) for item in domain.get('dimensions') or [])}",
            f"Synonyms: {', '.join(synonym_terms)}",
            f"Prompts: {' | '.join(str(prompt) for prompt in domain.get('query_studio_prompts') or [])}",
        ]
    )
    return {
        "workspace_id": workspace_id,
        "domain_id": int(domain_id),
        "summary": domain["description"],
        "keywords": _json_dumps(keywords),
        "entities": _json_dumps(entities),
        "metrics": _json_dumps(metrics),
        "attributes": _json_dumps(attributes),
        "synonyms": _json_dumps(synonyms),
        "acronyms": _json_dumps([]),
        "notes": notes,
        "embedding_text": embedding_text,
        "content_hash": hashlib.sha256(embedding_text.encode("utf-8")).hexdigest(),
    }


def _lookup_id(tx: Any, *, table_name: str, concept_key: str) -> int | None:
    if table_name not in {"semantic_concept", "semantic_registry"}:
        raise ValueError("unsupported semantic lookup table")
    rows = tx.execute_query_mappings(
        f"""
        SELECT id
        FROM {table_name}
        WHERE concept_key = :concept_key
        LIMIT 1
        """,
        {"concept_key": concept_key},
    )
    if not rows:
        return None
    return int(rows[0]["id"])


def _semantic_display_priority(semantic_type: str) -> int:
    return {
        "metric": 90,
        "attribute": 80,
        "time": 75,
        "flag": 70,
        "identifier": 60,
    }.get(str(semantic_type or "").strip().lower(), 40)


def _concept_description(*, domain: dict[str, Any], column_name: str, semantic: dict[str, str]) -> str:
    return (
        f"{semantic['description']} from {domain['display_name']} "
        f"({domain['read_model']}.{column_name}); generated Workflow Intelligence {semantic['semantic_type']}."
    )


def _semantic_aliases_for_column(
    *,
    domain: dict[str, Any],
    column_name: str,
    semantic: dict[str, str],
) -> list[dict[str, Any]]:
    semantic_type = str(semantic.get("semantic_type") or "").strip().lower()
    label = str(semantic.get("description") or "").strip()
    domain_name = str(domain.get("display_name") or "").strip()
    domain_key_words = str(domain.get("domain_key") or "").replace("_", " ")
    phrases = [
        label,
        column_name.replace("_", " "),
        f"{domain_name} {label}",
        f"{domain_key_words} {label}",
    ]
    if semantic_type in {"metric", "flag"}:
        phrases.extend(_metric_alias_phrases(label=label, column_name=column_name))
    aliases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for phrase in phrases:
        alias_key = _normalize_alias_text(phrase)
        if alias_key == "" or alias_key in seen or _is_generic_alias(alias_key):
            continue
        seen.add(alias_key)
        aliases.append(
            {
                "alias_key": alias_key[:200],
                "match_kind": "contains" if " " in alias_key else "exact",
                "weight": 1.0 if semantic_type == "metric" else 0.85,
            }
        )
    return aliases


def _metric_alias_phrases(*, label: str, column_name: str) -> list[str]:
    phrases: list[str] = []
    for raw in (label, column_name.replace("_", " ")):
        text = _normalize_alias_text(raw)
        for suffix in (
            " count",
            " flag",
            " runs",
            " run",
            " offers",
            " offer",
            " outcomes",
            " outcome",
            " records",
            " record",
        ):
            if text.endswith(suffix):
                phrases.append(text[: -len(suffix)])
        if text.endswith(" seconds"):
            phrases.append(text[: -len(" seconds")])
    return phrases


def _domain_profile_metric_config(
    *,
    item: dict[str, Any],
    domain: dict[str, Any],
    workspace_table_id: int | None,
    columns: list[dict[str, Any]],
    column_id_by_name: dict[str, int],
) -> dict[str, Any]:
    metric_key = str(item.get("key") or item.get("metric_key") or "").strip()
    label = str(item.get("label") or _field_label([item], metric_key)).strip() or metric_key
    binding = _metric_sql_binding(
        metric_key=metric_key,
        label=label,
        domain=domain,
        workspace_table_id=workspace_table_id,
        columns=columns,
        column_id_by_name=column_id_by_name,
    )
    agg = str((binding or {}).get("fn") or ("count" if metric_key.endswith("_count") else "sum")).strip().lower()
    out: dict[str, Any] = {
        "metric_key": metric_key,
        "label": label,
        "kind": "count" if agg == "count" else "numeric",
        "agg": agg,
        "column_key": (binding or {}).get("column_key"),
        "sql_metric": (binding or {}).get("sql_metric"),
    }
    if item.get("description"):
        out["description"] = str(item["description"])
    return out


def _metric_sql_binding(
    *,
    metric_key: str,
    label: str,
    domain: dict[str, Any],
    workspace_table_id: int | None,
    columns: list[dict[str, Any]],
    column_id_by_name: dict[str, int],
) -> dict[str, Any] | None:
    if workspace_table_id is None:
        return None
    column_names = {str(column.get("column_name") or "").strip() for column in columns}
    column_names.discard("")

    for column_name, fn in _metric_candidate_columns(metric_key=metric_key, domain=domain):
        if column_name not in column_names:
            continue
        column_id = column_id_by_name.get(column_name)
        if column_id is None:
            continue
        field = {
            "workspaceTableId": int(workspace_table_id),
            "modelColumnId": int(column_id),
            "columnName": column_name,
            "exprId": None,
        }
        return {
            "fn": fn,
            "column_key": f"wt{int(workspace_table_id)}.{column_name.lower()}",
            "sql_metric": {
                "fn": fn,
                "field": field,
                "label": label,
            },
        }
    return None


def _metric_candidate_columns(*, metric_key: str, domain: dict[str, Any]) -> list[tuple[str, str]]:
    key = str(metric_key or "").strip().lower()
    out: list[tuple[str, str]] = []
    if key:
        out.append((key, "sum"))
    if key.endswith("_count"):
        stem = key[: -len("_count")]
        out.extend(
            [
                (f"{stem}_flag", "sum"),
                (stem.removesuffix("_run") + "_flag", "sum"),
                (stem.removesuffix("_offer") + "_flag", "sum"),
                (stem.removesuffix("_outcome") + "_flag", "sum"),
                (stem.removesuffix("_artifact") + "_flag", "sum"),
            ]
        )
        if stem.endswith("_run"):
            run_stem = stem.removesuffix("_run")
            out.extend([(f"{run_stem}_at", "count"), (f"{run_stem}_reason", "count")])
        if stem.startswith("no_match"):
            out.append(("no_match_reason", "count"))
        if stem.startswith("selected"):
            out.append(("selected", "sum"))
        if stem.startswith("assigned"):
            out.append(("assigned_at", "count"))
        for identifier in domain.get("identifiers") or []:
            out.append((str(identifier), "count"))
        for fallback in ("id", "run_id", "event_id"):
            out.append((fallback, "count"))

    deduped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for column_name, fn in out:
        token = str(column_name or "").strip().lower()
        if not token:
            continue
        pair = (token, fn)
        if pair in seen:
            continue
        seen.add(pair)
        deduped.append(pair)
    return deduped


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _field_keys(items: Any) -> set[str]:
    out: set[str] = set()
    for item in list(items or []):
        if isinstance(item, dict):
            key = str(item.get("key") or item.get("metric_key") or "").strip()
        else:
            key = str(item or "").strip()
        if key:
            out.add(key)
    return out


def _field_label(items: Any, key: str) -> str:
    for item in list(items or []):
        if isinstance(item, dict) and str(item.get("key") or item.get("metric_key") or "").strip() == key:
            return str(item.get("label") or key).strip()
    return key.replace("_", " ").title()


def _synonym_text_terms(synonyms: list[dict[str, Any]]) -> list[str]:
    terms: list[str] = []
    for item in synonyms:
        raw_values = [item.get("term"), *list(item.get("means") or [])]
        for raw in raw_values:
            term = " ".join(str(raw or "").strip().split())
            if term and term not in terms:
                terms.append(term)
    return terms


def _normalize_alias_text(value: Any) -> str:
    return " ".join(str(value or "").replace("_", " ").strip().lower().split())


def _is_generic_alias(alias_key: str) -> bool:
    return alias_key in {
        "id",
        "status",
        "mode",
        "type",
        "source",
        "destination",
        "workflow",
        "resource",
        "created at",
        "updated at",
    }
