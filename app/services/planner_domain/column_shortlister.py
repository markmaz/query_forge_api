"""Column shortlist helpers for planner-domain selection."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping

from qdrant_client.http import models as qdrant_models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.services.planner_domain.capability_compactor import _merge_dimension_rows, _norm_key, _to_int
from app.services.planner_domain.column_scoring import (
    _cap_columns_per_table,
    _column_heuristic_boost,
    _extract_group_entities_for_shortlist,
    _has_group_entity,
    _prompt_prefers_staff_role_title_filter,
    _required_column_keys,
    _select_keys_with_table_cap,
)
from app.services.planner_domain.prompt_intents import (
    _dedupe_text_items,
    _looks_like_list_students_prompt,
    _prompt_has_adm_intent,
    _prompt_has_age_extreme,
    _prompt_has_birth_month_constraint,
    _prompt_has_subgroup,
    _prompt_implies_staff_work_context,
    _prompt_implies_student_school_context,
)

SHORTLIST_EMBEDDING_FALLBACK_ERRORS = (OSError, RuntimeError, ValueError)
SHORTLIST_VECTOR_FALLBACK_ERRORS = (OSError, RuntimeError, ValueError, UnexpectedResponse, ResponseHandlingException)


def _build_column_query_texts(prompt: str) -> List[str]:
    text = str(prompt or "").strip()
    out = [text]
    text_l = text.lower()
    group_entities = _extract_group_entities_for_shortlist(text_l)
    if _has_group_entity(group_entities, "account"):
        out.extend(["account name", "customer account"])
    if _has_group_entity(group_entities, "territory"):
        out.extend(["territory name", "sales territory"])
    if _has_group_entity(group_entities, "region"):
        out.extend(["region name"])
    if _prompt_has_subgroup(text):
        out.extend(["student race ethnicity", "student subgroup"])
    if _looks_like_list_students_prompt(text):
        out.extend(["student list", "student roster", "student demographics"])
    if _prompt_has_age_extreme(text):
        out.extend(["student birth date", "student date of birth", "student age"])
    if _prompt_has_birth_month_constraint(text):
        out.extend(["student birthday month", "student birth date month"])
    if _prompt_implies_staff_work_context(text):
        out.extend(["staff roster", "staff assignments", "teacher workplace", "employee school"])
    if _prompt_prefers_staff_role_title_filter(text):
        out.extend(["staff position title", "staff role title", "principal position"])
    if _prompt_implies_student_school_context(text):
        out.extend(["student enrollment", "student attends school", "student school"])
    if "county" in text_l:
        out.append("county district")
    if "district" in text_l:
        out.append("district lea")
    if "school year" in text_l or "this year" in text_l or "last year" in text_l:
        out.append("school year date")
    if _prompt_has_adm_intent(text):
        out.extend(
            [
                "average daily membership adm base adm",
                "normalized_adm report_period school_year",
                "is_primary_school grade_level_adm",
            ]
        )
    return _dedupe_text_items(out)


def shortlist_columns_for_domain(
    *,
    prompt: str,
    workspace_id: str,
    capabilities: Mapping[str, Any],
    embedding_model_factory: Callable[[], Any],
    column_vector_factory: Callable[[], Any],
) -> List[Dict[str, Any]]:
    all_rows = _merge_dimension_rows(
        dimensions=list(capabilities.get("dimensions") or []),
        time_columns=list(capabilities.get("time_columns") or []),
    )
    if not all_rows:
        return []

    by_key = {_norm_key(row.get("column_key")): row for row in all_rows if _norm_key(row.get("column_key"))}
    table_ids = sorted(
        {
            int(wtid)
            for wtid in (_to_int(row.get("workspace_table_id")) for row in all_rows)
            if wtid is not None
        }
    )
    if not table_ids:
        return all_rows[:40]

    query_texts = _build_column_query_texts(prompt)
    try:
        vectors = embedding_model_factory().encode(query_texts, normalize=True)
    except SHORTLIST_EMBEDDING_FALLBACK_ERRORS:
        return _cap_columns_per_table(all_rows, max_columns=50, per_table_cap=12)
    query_filter = qdrant_models.Filter(
        must=[
            qdrant_models.FieldCondition(
                key="kind",
                match=qdrant_models.MatchValue(value="column"),
            ),
            qdrant_models.FieldCondition(
                key="workspace_id",
                match=qdrant_models.MatchValue(value=str(workspace_id)),
            ),
            qdrant_models.FieldCondition(
                key="workspace_table_id",
                match=qdrant_models.MatchAny(any=table_ids),
            ),
        ]
    )

    by_score: Dict[str, float] = {}
    limit = min(max(len(all_rows), 80), 220)
    try:
        for vector in vectors:
            hits = column_vector_factory().search(
                vector=vector,
                limit=limit,
                query_filter=query_filter,
                with_payload=True,
            )
            for hit in hits:
                payload = hit.payload or {}
                wtid = _to_int(payload.get("workspace_table_id"))
                col = str(payload.get("column_name") or "").strip().lower()
                if wtid is None or col == "":
                    continue
                key = f"wt{wtid}.{col}"
                if key not in by_key:
                    continue
                score = float(hit.score or 0.0)
                if score > float(by_score.get(key) or 0.0):
                    by_score[key] = score
    except SHORTLIST_VECTOR_FALLBACK_ERRORS:
        return _cap_columns_per_table(all_rows, max_columns=50, per_table_cap=12)

    if not by_score:
        return _cap_columns_per_table(all_rows, max_columns=50, per_table_cap=12)

    for key, row in by_key.items():
        score = float(by_score.get(key) or 0.0)
        by_score[key] = score + _column_heuristic_boost(prompt=prompt, row=row)

    required_keys = _required_column_keys(prompt=prompt, rows=all_rows)
    ordered = sorted(by_score.items(), key=lambda item: item[1], reverse=True)
    selected_keys = _select_keys_with_table_cap(
        ordered_keys=[key for key, _ in ordered],
        row_by_key=by_key,
        max_columns=min(max(35, len(required_keys) + 25), 70),
        per_table_cap=12,
    )
    for key in required_keys:
        if key not in selected_keys and key in by_key:
            selected_keys.append(key)
    selected_keys = selected_keys[:70]
    return [dict(by_key[key]) for key in selected_keys if key in by_key]
