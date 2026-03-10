from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.ports.sql_executor import ForgeQueryPort

_WORD_RE = re.compile(r"[^a-z0-9]+")
_NUMERIC_DATA_TYPES = {
    "int",
    "integer",
    "bigint",
    "smallint",
    "tinyint",
    "float",
    "double",
    "decimal",
    "numeric",
    "real",
}
_DATE_DATA_TYPES = {"date", "datetime", "timestamp", "time"}


@dataclass(frozen=True)
class _CategorySeed:
    id: str
    label: str
    tokens: Tuple[str, ...]


class QueryStudioDomainExplorerService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def list_domains(self, *, workspace_id: str, user_id: str) -> List[Dict[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              d.id,
              d.name,
              d.description,
              COUNT(DISTINCT wc.id) AS field_count,
              COALESCE(
                MAX(
                  CASE
                    WHEN dp.entities IS NOT NULL AND JSON_VALID(dp.entities) THEN JSON_LENGTH(dp.entities)
                    ELSE 0
                  END
                ),
                0
              ) AS category_count,
              COALESCE(
                MAX(
                  CASE
                    WHEN dp.metrics IS NOT NULL AND JSON_VALID(dp.metrics) THEN JSON_LENGTH(dp.metrics)
                    ELSE 0
                  END
                ),
                0
              ) AS metric_count
            FROM user_domain_mapping udm
            JOIN domain d
              ON d.id = udm.domain_id
             AND d.workspace_id = :workspace_id
             AND d.is_active = 1
            LEFT JOIN domain_workspace_table dwt
              ON dwt.domain_id = d.id
            LEFT JOIN workspace_table wt
              ON wt.id = dwt.workspace_table_id
             AND wt.workspace_id = :workspace_id
             AND wt.exists_in_dbx = 1
            LEFT JOIN workspace_column wc
              ON wc.workspace_table_id = wt.id
            LEFT JOIN domain_profile dp
              ON dp.workspace_id = d.workspace_id
             AND dp.domain_id = d.id
            WHERE udm.user_id = :user_id
              AND udm.can_read = 1
            GROUP BY d.id, d.name, d.description
            ORDER BY d.name
            """,
            {"workspace_id": workspace_id, "user_id": user_id},
        )

        payload: List[Dict[str, Any]] = []
        for row in rows:
            domain_id = _as_int(row.get("id"))
            if domain_id is None:
                continue
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            payload.append(
                {
                    "id": domain_id,
                    "key": _slugify(name),
                    "label": name,
                    "description": str(row.get("description") or "").strip() or None,
                    "fieldCount": _as_int(row.get("field_count")) or 0,
                    "categoryCount": _as_int(row.get("category_count")) or 0,
                    "metricCount": _as_int(row.get("metric_count")) or 0,
                }
            )
        return payload

    def get_domain_explorer(
        self,
        *,
        workspace_id: str,
        user_id: str,
        domain_id: int,
    ) -> Dict[str, Any]:
        domain = self._load_domain(workspace_id=workspace_id, user_id=user_id, domain_id=domain_id)
        profile = self._load_domain_profile(workspace_id=workspace_id, domain_id=domain_id)
        raw_fields = self._load_domain_fields(workspace_id=workspace_id, domain_id=domain_id)

        aliases_by_field = _build_alias_index(_parse_json_list(profile.get("synonyms")))
        fields = self._build_fields(raw_fields=raw_fields, aliases_by_field=aliases_by_field)
        categories = self._build_categories(fields=fields, profile=profile)
        recommended = self._build_recommended_fields(fields=fields, profile=profile)

        metric_count = max(
            _as_int(domain.get("metric_count")) or 0,
            len(_parse_json_list(profile.get("metrics"))),
        )
        category_count = max(_as_int(domain.get("category_count")) or 0, len(categories))
        domain_summary = {
            "id": _as_int(domain.get("id")),
            "key": _slugify(str(domain.get("name") or "")),
            "label": str(domain.get("name") or "").strip(),
            "description": str(domain.get("description") or "").strip() or None,
            "fieldCount": max(_as_int(domain.get("field_count")) or 0, len(fields)),
            "categoryCount": category_count,
            "metricCount": metric_count,
            "exampleQuestions": self._extract_example_questions(profile),
        }

        return {
            "domain": domain_summary,
            "recommendedFields": recommended,
            "fieldCategories": categories,
        }

    def _load_domain(
        self,
        *,
        workspace_id: str,
        user_id: str,
        domain_id: int,
    ) -> Mapping[str, Any]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              d.id,
              d.name,
              d.description,
              COUNT(DISTINCT wc.id) AS field_count,
              COALESCE(
                MAX(
                  CASE
                    WHEN dp.entities IS NOT NULL AND JSON_VALID(dp.entities) THEN JSON_LENGTH(dp.entities)
                    ELSE 0
                  END
                ),
                0
              ) AS category_count,
              COALESCE(
                MAX(
                  CASE
                    WHEN dp.metrics IS NOT NULL AND JSON_VALID(dp.metrics) THEN JSON_LENGTH(dp.metrics)
                    ELSE 0
                  END
                ),
                0
              ) AS metric_count
            FROM domain d
            JOIN user_domain_mapping udm
              ON udm.domain_id = d.id
             AND udm.user_id = :user_id
             AND udm.can_read = 1
            LEFT JOIN domain_workspace_table dwt
              ON dwt.domain_id = d.id
            LEFT JOIN workspace_table wt
              ON wt.id = dwt.workspace_table_id
             AND wt.workspace_id = :workspace_id
             AND wt.exists_in_dbx = 1
            LEFT JOIN workspace_column wc
              ON wc.workspace_table_id = wt.id
            LEFT JOIN domain_profile dp
              ON dp.workspace_id = d.workspace_id
             AND dp.domain_id = d.id
            WHERE d.workspace_id = :workspace_id
              AND d.id = :domain_id
              AND d.is_active = 1
            GROUP BY d.id, d.name, d.description
            LIMIT 1
            """,
            {"workspace_id": workspace_id, "user_id": user_id, "domain_id": int(domain_id)},
        )
        if not rows:
            raise ForgeError("Domain not found or access denied", status_code=404)
        return rows[0]

    def _load_domain_profile(self, *, workspace_id: str, domain_id: int) -> Mapping[str, Any]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT summary, entities, metrics, attributes, synonyms, notes
            FROM domain_profile
            WHERE workspace_id = :workspace_id
              AND domain_id = :domain_id
            LIMIT 1
            """,
            {"workspace_id": workspace_id, "domain_id": int(domain_id)},
        )
        return rows[0] if rows else {}

    def _load_domain_fields(self, *, workspace_id: str, domain_id: int) -> List[Mapping[str, Any]]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              wc.id AS workspace_column_id,
              COALESCE(wc.model_column_id, wc.id) AS model_column_id,
              wc.column_name,
              wc.data_type,
              wc.description,
              wt.table_name,
              dwt.table_alias,
              wc.ordinal_position
            FROM domain_workspace_table dwt
            JOIN workspace_table wt
              ON wt.id = dwt.workspace_table_id
             AND wt.workspace_id = :workspace_id
             AND wt.exists_in_dbx = 1
            JOIN workspace_column wc
              ON wc.workspace_table_id = wt.id
            WHERE dwt.domain_id = :domain_id
            ORDER BY
              CASE WHEN dwt.is_primary = 1 THEN 0 ELSE 1 END,
              dwt.sort_order ASC,
              wt.table_name ASC,
              wc.ordinal_position ASC
            """,
            {"workspace_id": workspace_id, "domain_id": int(domain_id)},
        )
        return list(rows)

    def _build_fields(
        self,
        *,
        raw_fields: Sequence[Mapping[str, Any]],
        aliases_by_field: Mapping[str, List[str]],
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        seen_paths: set[str] = set()
        for row in raw_fields:
            column_name = str(row.get("column_name") or "").strip()
            if not column_name:
                continue
            table_label = str(row.get("table_alias") or row.get("table_name") or "").strip()
            if not table_label:
                table_label = "domain"

            path = f"{table_label}.{column_name}"
            dedupe_key = path.lower()
            if dedupe_key in seen_paths:
                continue
            seen_paths.add(dedupe_key)

            data_type = str(row.get("data_type") or "").strip().lower() or None
            key = _slugify(column_name)
            field_id = _as_int(row.get("model_column_id"))
            if field_id is None:
                workspace_column_id = _as_int(row.get("workspace_column_id"))
                field_id = f"wc_{workspace_column_id}" if workspace_column_id is not None else path

            aliases = aliases_by_field.get(key, [])
            field = {
                "id": field_id,
                "key": key,
                "label": _friendly_label(column_name=column_name, description=row.get("description")),
                "path": path,
                "dataType": data_type,
                "aliases": aliases,
                "allowedAggregations": _allowed_aggregations(data_type),
            }
            out.append(field)
        return out

    def _build_categories(
        self,
        *,
        fields: Sequence[Mapping[str, Any]],
        profile: Mapping[str, Any],
    ) -> List[Dict[str, Any]]:
        seeds = self._category_seeds(profile)
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        labels_by_id: Dict[str, str] = {}

        for field in fields:
            category = _pick_category(field=field, seeds=seeds)
            labels_by_id[category.id] = category.label
            grouped.setdefault(category.id, []).append(dict(field))

        ordered_ids = sorted(grouped.keys(), key=lambda key: (-len(grouped[key]), labels_by_id.get(key, key)))
        return [{"id": category_id, "label": labels_by_id[category_id], "fields": grouped[category_id]} for category_id in ordered_ids]

    def _category_seeds(self, profile: Mapping[str, Any]) -> List[_CategorySeed]:
        seeds: List[_CategorySeed] = []
        for item in _parse_json_list(profile.get("entities")) + _parse_json_list(profile.get("attributes")):
            label = _label_from_unknown(item)
            if not label:
                continue
            normalized = _slugify(label)
            if not normalized:
                continue
            tokens = tuple(_tokenize(label))
            if not tokens:
                continue
            if any(seed.id == normalized for seed in seeds):
                continue
            seeds.append(_CategorySeed(id=normalized, label=label.strip(), tokens=tokens))
        return seeds[:8]

    def _build_recommended_fields(
        self,
        *,
        fields: Sequence[Mapping[str, Any]],
        profile: Mapping[str, Any],
    ) -> List[Dict[str, Any]]:
        metric_tokens = {_slugify(_label_from_unknown(metric)) for metric in _parse_json_list(profile.get("metrics"))}
        metric_tokens.discard("")
        scored: List[Tuple[float, Dict[str, Any]]] = []

        for field in fields:
            key = str(field.get("key") or "")
            label = str(field.get("label") or "")
            path = str(field.get("path") or "")
            data_type = str(field.get("dataType") or "")
            token_blob = " ".join((key, label.lower(), path.lower()))
            score = 0.0

            if key in metric_tokens:
                score += 5.0
            if data_type in _NUMERIC_DATA_TYPES:
                score += 2.0
            if any(token in token_blob for token in ("revenue", "amount", "total", "count", "rate", "score", "units")):
                score += 1.75
            if any(token in token_blob for token in ("date", "month", "year", "time")):
                score += 1.5
            if any(token in token_blob for token in ("name", "status", "category", "type", "territory", "school")):
                score += 1.0
            if any(token in token_blob for token in ("_id", " id", "key", "code")):
                score -= 0.5

            scored.append((score, dict(field)))

        scored.sort(key=lambda item: (-item[0], str(item[1].get("label") or "").lower()))
        return [item[1] for item in scored[:10]]

    def _extract_example_questions(self, profile: Mapping[str, Any]) -> List[str]:
        notes = str(profile.get("notes") or "").strip()
        if not notes:
            return []
        candidates = [line.strip(" -•\t") for line in notes.splitlines() if "?" in line]
        deduped: List[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if not candidate:
                continue
            key = candidate.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return deduped[:3]


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _friendly_label(*, column_name: str, description: Any) -> str:
    description_text = str(description or "").strip()
    if description_text and len(description_text) <= 64 and " " in description_text:
        return description_text
    return " ".join(word.capitalize() for word in column_name.replace("_", " ").split())


def _allowed_aggregations(data_type: Optional[str]) -> List[str]:
    dt = (data_type or "").lower()
    if dt in _NUMERIC_DATA_TYPES:
        return ["sum", "avg", "min", "max", "count"]
    if dt in _DATE_DATA_TYPES:
        return ["min", "max", "count"]
    if dt in {"bool", "boolean"}:
        return ["count"]
    return ["count"]


def _slugify(value: Any) -> str:
    lowered = str(value or "").strip().lower()
    return "_".join(token for token in _WORD_RE.sub(" ", lowered).split() if token)


def _tokenize(value: Any) -> List[str]:
    return [token for token in _slugify(value).split("_") if token]


def _parse_json_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="ignore")
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []


def _label_from_unknown(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        for key in ("label", "name", "term", "key"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item
    return str(value)


def _build_alias_index(synonyms: Sequence[Any]) -> Dict[str, List[str]]:
    alias_map: Dict[str, List[str]] = {}
    for item in synonyms:
        if not isinstance(item, Mapping):
            continue
        term = _slugify(item.get("term"))
        raw_means = item.get("means")
        if isinstance(raw_means, (list, tuple, set)):
            means = list(raw_means)
        else:
            means = []
        mean_tokens = [_slugify(mean) for mean in means if _slugify(mean)]
        if term and mean_tokens:
            alias_map.setdefault(term, [])
            for alias in mean_tokens:
                if alias not in alias_map[term]:
                    alias_map[term].append(alias)
        for alias in mean_tokens:
            alias_map.setdefault(alias, [])
            if term and term not in alias_map[alias]:
                alias_map[alias].append(term)
    return alias_map


def _pick_category(*, field: Mapping[str, Any], seeds: Sequence[_CategorySeed]) -> _CategorySeed:
    label = str(field.get("label") or "")
    key = str(field.get("key") or "")
    path = str(field.get("path") or "")
    token_set = set(_tokenize(" ".join((label, key, path))))

    best_seed: Optional[_CategorySeed] = None
    best_score = 0
    for seed in seeds:
        overlap = len(token_set.intersection(seed.tokens))
        if overlap > best_score:
            best_score = overlap
            best_seed = seed

    if best_seed and best_score > 0:
        return best_seed

    data_type = str(field.get("dataType") or "").lower()
    if any(token in key for token in ("date", "time", "month", "year")) or data_type in _DATE_DATA_TYPES:
        return _CategorySeed(id="time_periods", label="Time & Periods", tokens=("time", "date", "period"))
    if any(token in key for token in ("id", "key", "code")):
        return _CategorySeed(id="identifiers", label="Identifiers", tokens=("identifier", "id", "code"))
    if data_type in _NUMERIC_DATA_TYPES:
        return _CategorySeed(id="measures", label="Measures", tokens=("measure", "metric", "value"))
    if any(token in key for token in ("status", "type", "category", "name")):
        return _CategorySeed(id="dimensions", label="Dimensions", tokens=("dimension", "attribute"))
    return _CategorySeed(id="attributes", label="Attributes", tokens=("attribute",))


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value
