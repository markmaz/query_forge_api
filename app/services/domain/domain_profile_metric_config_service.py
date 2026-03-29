from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Optional

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.models.domain.domain_profile import DomainProfileBase, _build_embedding_text, compute_content_hash
from app.ports.sql_executor import ForgeQueryPort

_ALLOWED_AGGS = {"count", "count_distinct", "sum", "avg", "min", "max"}
_ALLOWED_KINDS = {"count", "numeric", "ratio", "custom"}
_NAME_TOKEN_RE = re.compile(r"[^a-z0-9]+")
_COLUMN_KEY_RE = re.compile(r"^wt\d+\.[a-z0-9_]+$")


class DomainProfileMetricConfigService:
    def __init__(self, *, sql: Optional[ForgeQueryPort] = None) -> None:
        self._sql = sql or ForgeMetaSQL()

    def get_profile_metrics(
        self,
        *,
        workspace_id: str,
        user_id: str,
        domain_id: int,
    ) -> Dict[str, Any]:
        row = self._load_domain_profile_row(
            workspace_id=workspace_id,
            user_id=user_id,
            domain_id=domain_id,
        )
        metrics = _normalize_metric_entries(_parse_json(row.get("metrics")) or [])
        return {
            "domain_id": int(row["domain_id"]),
            "domain_name": str(row.get("domain_name") or "").strip() or None,
            "metrics": metrics,
            "has_profile": row.get("profile_id") is not None,
            "can_edit": bool(row.get("can_edit")),
        }

    def update_profile_metrics(
        self,
        *,
        workspace_id: str,
        user_id: str,
        domain_id: int,
        metrics_payload: Any,
    ) -> Dict[str, Any]:
        row = self._load_domain_profile_row(
            workspace_id=workspace_id,
            user_id=user_id,
            domain_id=domain_id,
        )
        if not bool(row.get("can_edit")):
            raise ForgeError("You do not have edit permission for this domain.", status_code=403)

        metrics = _normalize_metric_entries(metrics_payload)
        profile_base = DomainProfileBase(
            summary=_clean_text(row.get("summary")),
            keywords=_parse_json(row.get("keywords")),
            entities=_parse_json(row.get("entities")),
            metrics=metrics,
            attributes=_parse_json(row.get("attributes")),
            synonyms=_parse_json(row.get("synonyms")),
            acronyms=_parse_json(row.get("acronyms")),
            notes=_clean_text(row.get("notes")),
        )
        embedding_text = _build_embedding_text(profile_base)
        content_hash = compute_content_hash(embedding_text)

        params = {
            "workspace_id": str(workspace_id),
            "domain_id": int(domain_id),
            "summary": profile_base.summary,
            "keywords": _json_dumps(profile_base.keywords),
            "entities": _json_dumps(profile_base.entities),
            "metrics": _json_dumps(metrics),
            "attributes": _json_dumps(profile_base.attributes),
            "synonyms": _json_dumps(profile_base.synonyms),
            "acronyms": _json_dumps(profile_base.acronyms),
            "notes": profile_base.notes,
            "embedding_text": embedding_text,
            "content_hash": content_hash,
        }

        profile_id = row.get("profile_id")
        with self._sql.transaction() as tx:
            if profile_id is None:
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
                      content_hash
                    ) VALUES (
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
                      :content_hash
                    )
                    """,
                    params,
                )
            else:
                tx.execute_write(
                    """
                    UPDATE domain_profile
                    SET metrics = :metrics,
                        embedding_text = :embedding_text,
                        content_hash = :content_hash,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = :profile_id
                      AND workspace_id = :workspace_id
                      AND domain_id = :domain_id
                    """,
                    {**params, "profile_id": int(profile_id)},
                )

        return self.get_profile_metrics(
            workspace_id=workspace_id,
            user_id=user_id,
            domain_id=domain_id,
        )

    def _load_domain_profile_row(
        self,
        *,
        workspace_id: str,
        user_id: str,
        domain_id: int,
    ) -> Dict[str, Any]:
        rows = self._sql.execute_query_mappings(
            """
            SELECT
              d.id AS domain_id,
              d.name AS domain_name,
              udm.can_edit,
              dp.id AS profile_id,
              dp.summary,
              dp.keywords,
              dp.entities,
              dp.metrics,
              dp.attributes,
              dp.synonyms,
              dp.acronyms,
              dp.notes
            FROM domain d
            JOIN user_domain_mapping udm
              ON udm.domain_id = d.id
             AND udm.user_id = :user_id
             AND udm.can_read = 1
            LEFT JOIN domain_profile dp
              ON dp.workspace_id = d.workspace_id
             AND dp.domain_id = d.id
            WHERE d.workspace_id = :workspace_id
              AND d.id = :domain_id
              AND d.is_active = 1
            LIMIT 1
            """,
            {
                "workspace_id": str(workspace_id),
                "user_id": str(user_id),
                "domain_id": int(domain_id),
            },
        )
        if not rows:
            raise ForgeError("Domain not found or access denied", status_code=404)
        return dict(rows[0])


def _normalize_metric_entries(value: Any) -> List[Dict[str, Any]]:
    raw_items = value
    if raw_items is None:
        return []
    if not isinstance(raw_items, list):
        raise ForgeError("'metrics' must be a list", status_code=400)

    out: List[Dict[str, Any]] = []
    by_key: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for idx, item in enumerate(raw_items):
        metric = _normalize_metric_item(item=item, idx=idx)
        key = str(metric["metric_key"])
        if key not in by_key:
            order.append(key)
        by_key[key] = metric

    for key in order:
        out.append(by_key[key])
    return out


def _normalize_metric_item(*, item: Any, idx: int) -> Dict[str, Any]:
    if isinstance(item, str):
        metric_key = _to_metric_key(item)
        if metric_key == "":
            raise ForgeError(f"metrics[{idx}] is empty", status_code=400)
        return {
            "metric_key": metric_key,
            "label": _metric_label(metric_key),
            "kind": _infer_metric_kind(metric_key),
            "agg": _default_metric_agg(metric_key),
            "column_key": None,
            "sql_metric": None,
        }

    if not isinstance(item, Mapping):
        raise ForgeError(f"metrics[{idx}] must be a string or object", status_code=400)

    metric_key = _to_metric_key(item.get("metric_key") or item.get("key") or item.get("name"))
    if metric_key == "":
        raise ForgeError(f"metrics[{idx}].metric_key is required", status_code=400)

    kind = str(item.get("kind") or _infer_metric_kind(metric_key)).strip().lower()
    if kind not in _ALLOWED_KINDS:
        raise ForgeError(
            f"metrics[{idx}].kind must be one of: {', '.join(sorted(_ALLOWED_KINDS))}",
            status_code=400,
        )

    agg = str(item.get("agg") or _default_metric_agg(metric_key)).strip().lower()
    if agg not in _ALLOWED_AGGS:
        raise ForgeError(
            f"metrics[{idx}].agg must be one of: {', '.join(sorted(_ALLOWED_AGGS))}",
            status_code=400,
        )

    label = str(item.get("label") or _metric_label(metric_key)).strip() or _metric_label(metric_key)
    column_key = _normalize_column_key(item.get("column_key"), idx=idx)
    sql_metric = item.get("sql_metric")
    if sql_metric is not None and not isinstance(sql_metric, Mapping):
        raise ForgeError(f"metrics[{idx}].sql_metric must be an object", status_code=400)

    return {
        "metric_key": metric_key,
        "label": label,
        "kind": kind,
        "agg": agg,
        "column_key": column_key,
        "sql_metric": dict(sql_metric) if isinstance(sql_metric, Mapping) else None,
    }


def _normalize_column_key(value: Any, *, idx: int) -> Optional[str]:
    token = str(value or "").strip().lower()
    if token == "":
        return None
    if _COLUMN_KEY_RE.match(token) is None:
        raise ForgeError(
            f"metrics[{idx}].column_key must look like wt<id>.<column_name>",
            status_code=400,
        )
    return token


def _to_metric_key(value: Any) -> str:
    token = _norm_token_blob(value)
    return "_".join(token.split())


def _metric_label(value: Any) -> str:
    text = str(value or "").replace("_", " ").strip()
    return " ".join(word.capitalize() for word in text.split())


def _infer_metric_kind(metric_key: str) -> str:
    key = str(metric_key or "").strip().lower()
    if "ratio" in key or "rate" in key or "_per_" in key or key.endswith("_pct") or "percent" in key:
        return "ratio"
    if "count" in key:
        return "count"
    return "numeric"


def _default_metric_agg(metric_key: str) -> str:
    kind = _infer_metric_kind(metric_key)
    if kind == "count":
        return "count"
    if kind == "ratio":
        return "count_distinct"
    return "sum"


def _norm_token_blob(text: Any) -> str:
    return " ".join(_NAME_TOKEN_RE.sub(" ", str(text or "").strip().lower()).split())


def _parse_json(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="ignore")
    text = str(value or "").strip()
    if text == "":
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _json_dumps(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _clean_text(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


__all__ = ["DomainProfileMetricConfigService"]

