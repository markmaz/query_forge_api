from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.config import VLLM_BASE_URL, VLLM_MODEL, VLLM_TIMEOUT
from app.models.query.ai_suggest import (
    AddAggregateEdit,
    AddGroupByEdit,
    AddSelectEdit,
    AddSortEdit,
    SetDomainEdit,
    SqlColumnKey,
    SuggestAPIResponse,
    SuggestModelResponse,
    SuggestRequest,
)
from app.ports.sql_executor import ForgeQueryPort
from app.services.ai_suggest.domain_seeder import DomainSeeder
from app.services.ai_suggest.edit_enforcer import EditEnforcer
from app.services.ai_suggest.edit_inspector import (
    _column_ref_identity,
    count_add_select_edits,
    determine_default_aggregate_column,
    determine_default_groupby_columns,
    determine_default_sort,
    edits_have_aggregate,
    edits_have_groupby,
    edits_have_sorting,
    edits_reference_columns,
    extract_column_refs_from_edits,
    get_identifier_candidates,
    has_identifier_projection,
    is_aggregation_only,
)
from app.services.ai_suggest.prompt_analysis import (
    prompt_contains_literal,
    prompt_implies_aggregation,
    prompt_implies_entity_listing,
    prompt_implies_grouping,
    prompt_implies_sorting,
    prompt_requests_distinct_count,
)
from app.services.ai_suggest.prompt_builder import PromptBuilder
from app.services.ai_suggest.response_normalizer import ResponseNormalizer
from app.services.ai_suggest.utils import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
)
from app.services.ai_suggest.vllm_client import VllmClient
from app.services.sqljson_apply_service import apply_edits

logger = logging.getLogger(__name__)


class InvalidModelResponseError(RuntimeError):
    """Raised when model output cannot be parsed/validated after retry."""

    def __init__(self, details: Dict[str, Any]):
        super().__init__("Invalid model response")
        self.details = details


class AISuggestService:
    """Generates structured planner edits via a local vLLM chat endpoint."""

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
        temperature: float = DEFAULT_TEMPERATURE,
        top_p: float = DEFAULT_TOP_P,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        sql_executor: Optional[ForgeQueryPort] = None,
    ) -> None:
        self.base_url = (base_url or VLLM_BASE_URL).rstrip("/")
        self.model = model or VLLM_MODEL
        timeout_value = timeout if timeout is not None else VLLM_TIMEOUT
        self.timeout = int(timeout_value)
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max(600, min(800, int(max_tokens)))
        self._sql = sql_executor or ForgeMetaSQL()
        self._vllm_client = VllmClient(
            base_url=self.base_url,
            model=self.model,
            timeout=self.timeout,
            temperature=self.temperature,
            top_p=self.top_p,
            max_tokens=self.max_tokens,
        )
        self._prompt_builder = PromptBuilder()
        self._response_normalizer = ResponseNormalizer()
        self._edit_enforcer = EditEnforcer()
        self._domain_seeder = DomainSeeder(sql_executor=self._sql)

    def suggest(
        self,
        suggest_request: SuggestRequest,
        *,
        valid_domain_ids: Optional[set[int]] = None,
        valid_column_keys: Optional[set[str]] = None,
    ) -> SuggestAPIResponse:
        start = time.perf_counter()
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": self._prompt_builder.build_system_prompt()},
            {"role": "user", "content": self._prompt_builder.build_user_prompt(suggest_request)},
        ]
        candidate_columns = suggest_request.candidates.columns if suggest_request.candidates else []
        candidate_column_dicts = [candidate.model_dump(mode="json") for candidate in candidate_columns]
        literal_detected = prompt_contains_literal(suggest_request.prompt)
        logger.info(
            "AI suggest prompt=%s literal_detected=%s",
            suggest_request.prompt,
            literal_detected,
        )
        previous_content = ""
        last_error: Dict[str, Any] = {}
        retry_reason: Optional[str] = None
        fallback_response: Optional[SuggestAPIResponse] = None

        for attempt in (1, 2):
            attempt_messages = list(messages)
            if attempt == 2:
                if retry_reason == "missing_filters":
                    attempt_messages.append(
                        {"role": "system", "content": self._prompt_builder.build_filter_retry_prompt()}
                    )
                elif retry_reason == "missing_domain":
                    attempt_messages.append(
                        {"role": "system", "content": self._prompt_builder.build_domain_retry_prompt()}
                    )
                elif retry_reason == "missing_aggregate":
                    attempt_messages.append(
                        {"role": "system", "content": self._prompt_builder.build_aggregate_retry_prompt()}
                    )
                elif retry_reason == "missing_groupby":
                    attempt_messages.append(
                        {"role": "system", "content": self._prompt_builder.build_groupby_retry_prompt()}
                    )
                elif retry_reason == "missing_projection_completeness":
                    attempt_messages.append(
                        {
                            "role": "system",
                            "content": self._prompt_builder.build_projection_completeness_retry_prompt(),
                        }
                    )
                else:
                    attempt_messages.append(
                        {
                            "role": "system",
                            "content": self._prompt_builder.build_repair_prompt(previous_content),
                        }
                    )

            raw = self._vllm_client.call(attempt_messages)
            try:
                content = self._vllm_client.extract_content(raw)
            except InvalidModelResponseError as exc:
                last_error = {"attempt": attempt, **exc.details}
                logger.warning("AI suggest response content extraction failed on attempt %s: %s", attempt, exc.details)
                retry_reason = "repair"
                if attempt == 2 and fallback_response is not None:
                    logger.error(
                        "AI suggest retry failed to return parsable content; returning first valid response without filters"
                    )
                    return fallback_response
                continue
            previous_content = content
            self._prompt_builder.log_raw_model_output(attempt, content)

            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as exc:
                last_error = {
                    "attempt": attempt,
                    "type": "json_parse_error",
                    "message": str(exc),
                    "content": content,
                }
                logger.warning("AI suggest JSON parse failed on attempt %s: %s", attempt, exc)
                retry_reason = "repair"
                if attempt == 2 and fallback_response is not None:
                    logger.error(
                        "AI suggest retry returned invalid JSON; returning first valid response without filters"
                    )
                    return fallback_response
                continue

            normalized, normalization_meta = self._response_normalizer.normalize(parsed)

            try:
                validated = SuggestModelResponse.model_validate(normalized)
                grounded, removed_count = self._edit_enforcer.enforce_grounding(
                    validated=validated,
                    valid_domain_ids=valid_domain_ids,
                    valid_column_keys=valid_column_keys,
                )
                edits_dicts = [edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits]
                llm_emitted_set_domain = any(str(edit.get("op") or "") == "setDomain" for edit in edits_dicts)
                llm_emitted_add_select = any(str(edit.get("op") or "") == "addSelect" for edit in edits_dicts)
                logger.info(
                    "AI suggest domain signal attempt=%s llm_emitted_set_domain=%s llm_emitted_add_select=%s",
                    attempt,
                    llm_emitted_set_domain,
                    llm_emitted_add_select,
                )

                inferred_domain_id: Optional[int] = None
                needs_domain = edits_reference_columns(edits_dicts)
                if not llm_emitted_set_domain and needs_domain:
                    inferred_domain_id = self._domain_seeder.current_sqljson_domain_id(suggest_request.currentSqlJson)
                    if inferred_domain_id is not None:
                        logger.info("Domain taken from currentSqlJson: %s", inferred_domain_id)
                    else:
                        inferred_domain_id = self._domain_seeder.fallback_domain_id(suggest_request)
                        if inferred_domain_id is not None:
                            logger.info(
                                "Domain inferred from request context fallback: %s",
                                inferred_domain_id,
                            )
                        else:
                            inferred_domain_id = self._domain_seeder.infer_domain_safely(
                                workspace_id=suggest_request.workspaceId,
                                edits=edits_dicts,
                            )
                    if inferred_domain_id is not None:
                        grounded = SuggestModelResponse(
                            edits=[SetDomainEdit(op="setDomain", domainId=int(inferred_domain_id)), *grounded.edits],
                            explanation=grounded.explanation,
                            confidence=grounded.confidence,
                        )
                        edits_dicts = [edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits]
                        logger.info("Domain inferred deterministically: %s", inferred_domain_id)
                    elif attempt == 1:
                        logger.warning(
                            "Missing required setDomain edit with column edits. Retrying with stricter instruction."
                        )
                        retry_reason = "missing_domain"
                        continue
                    else:
                        logger.warning("Unable to determine domain.")

                projection_injected = 0
                if not is_aggregation_only(edits_dicts):
                    referenced_cols = extract_column_refs_from_edits(edits_dicts)
                    has_add_select = any(str(edit.get("op") or "") == "addSelect" for edit in edits_dicts)
                    if referenced_cols and not has_add_select:
                        injected_selects: list[AddSelectEdit] = []
                        existing_select_keys = {
                            _column_ref_identity(edit.get("col") or {})
                            for edit in edits_dicts
                            if isinstance(edit, dict)
                            and str(edit.get("op") or "") == "addSelect"
                            and isinstance(edit.get("col"), dict)
                        }
                        for col in referenced_cols:
                            if not isinstance(col, dict):
                                continue
                            if str(col.get("columnName") or "").strip() == "":
                                continue
                            identity = _column_ref_identity(col)
                            if identity in existing_select_keys:
                                continue
                            try:
                                select_edit = AddSelectEdit(
                                    op="addSelect",
                                    col=SqlColumnKey.model_validate(col),
                                    alias=str(col.get("columnName") or "").strip() or None,
                                )
                            except Exception:
                                continue
                            injected_selects.append(select_edit)
                            existing_select_keys.add(identity)
                        if injected_selects:
                            logger.info("Projection fallback triggered — injecting addSelect edits.")
                            projection_injected = len(injected_selects)
                            grounded = SuggestModelResponse(
                                edits=[*injected_selects, *grounded.edits],
                                explanation=grounded.explanation,
                                confidence=grounded.confidence,
                            )
                            edits_dicts = [edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits]
                logger.info("AI suggest projection fallback injected_count=%s", projection_injected)

                aggregation_intent = prompt_implies_aggregation(suggest_request.prompt)
                has_aggregate = edits_have_aggregate(edits_dicts)
                aggregation_fallback_injected = False
                logger.info(
                    "AI suggest aggregation signal attempt=%s aggregation_intent=%s llm_emitted_aggregate=%s",
                    attempt,
                    aggregation_intent,
                    has_aggregate,
                )
                if aggregation_intent and not has_aggregate:
                    if attempt == 1:
                        logger.warning("Missing required addAggregate edit. Retrying with stricter instruction.")
                        retry_reason = "missing_aggregate"
                        continue
                    default_agg_col = determine_default_aggregate_column(edits_dicts)
                    if default_agg_col is not None:
                        try:
                            agg_edit = AddAggregateEdit(
                                op="addAggregate",
                                func="count",
                                col=SqlColumnKey.model_validate(default_agg_col),
                                alias="count_result",
                            )
                            grounded = SuggestModelResponse(
                                edits=[*grounded.edits, agg_edit],
                                explanation=grounded.explanation,
                                confidence=grounded.confidence,
                            )
                            edits_dicts = [edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits]
                            aggregation_fallback_injected = True
                            logger.info("Aggregation fallback triggered — injecting addAggregate.")
                        except Exception as exc:
                            logger.warning("Aggregation fallback failed to inject addAggregate: %s", exc)
                    else:
                        logger.warning("Aggregation implied but no column available for fallback.")

                distinct_requested = prompt_requests_distinct_count(suggest_request.prompt)
                grounded, distinct_normalized_count = self._edit_enforcer.normalize_distinct_aggregate(
                    grounded,
                    distinct_requested=distinct_requested,
                )
                if distinct_normalized_count > 0:
                    edits_dicts = [edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits]
                    logger.info(
                        "AI suggest aggregate distinct policy normalized_count=%s distinct_requested=%s",
                        distinct_normalized_count,
                        distinct_requested,
                    )

                grounded, geo_filter_expansion_count = self._edit_enforcer.normalize_geography_filter_aliases(grounded)
                if geo_filter_expansion_count > 0:
                    edits_dicts = [edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits]
                    logger.info("AI suggest geography filter expansion count=%s", geo_filter_expansion_count)

                grouping_intent = prompt_implies_grouping(suggest_request.prompt)
                has_group_by = edits_have_groupby(edits_dicts)
                grouping_injected_count = 0
                logger.info(
                    "AI suggest grouping signal attempt=%s grouping_intent=%s llm_emitted_groupby=%s",
                    attempt,
                    grouping_intent,
                    has_group_by,
                )
                if grouping_intent and not has_group_by:
                    if attempt == 1:
                        logger.warning("Missing required addGroupBy edit. Retrying with stricter instruction.")
                        retry_reason = "missing_groupby"
                        continue
                    default_group_cols = determine_default_groupby_columns(edits_dicts)
                    if default_group_cols:
                        existing_group_keys = {
                            _column_ref_identity(edit.get("col") or {})
                            for edit in edits_dicts
                            if isinstance(edit, dict)
                            and str(edit.get("op") or "") == "addGroupBy"
                            and isinstance(edit.get("col"), dict)
                        }
                        injected_groupby: list[AddGroupByEdit] = []
                        for col in default_group_cols:
                            if not isinstance(col, dict):
                                continue
                            identity = _column_ref_identity(col)
                            if identity in existing_group_keys:
                                continue
                            try:
                                group_edit = AddGroupByEdit(
                                    op="addGroupBy",
                                    col=SqlColumnKey.model_validate(col),
                                )
                            except Exception:
                                continue
                            injected_groupby.append(group_edit)
                            existing_group_keys.add(identity)
                        if injected_groupby:
                            grounded = SuggestModelResponse(
                                edits=[*injected_groupby, *grounded.edits],
                                explanation=grounded.explanation,
                                confidence=grounded.confidence,
                            )
                            edits_dicts = [edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits]
                            grouping_injected_count = len(injected_groupby)
                            logger.info("Grouping fallback triggered — injecting addGroupBy edits.")
                    else:
                        logger.warning("Grouping implied but no column available for fallback.")

                sorting_intent = prompt_implies_sorting(suggest_request.prompt)
                has_sorting = edits_have_sorting(edits_dicts)
                sorting_injected = False
                logger.info(
                    "AI suggest sorting signal attempt=%s sorting_intent=%s llm_emitted_sorting=%s",
                    attempt,
                    sorting_intent,
                    has_sorting,
                )
                if sorting_intent and not has_sorting:
                    default_sort = determine_default_sort(edits_dicts, suggest_request.prompt)
                    if default_sort is not None:
                        try:
                            sort_edit = AddSortEdit(
                                op="addSort",
                                col=SqlColumnKey.model_validate(default_sort["col"]),
                                dir=str(default_sort.get("dir") or "asc").lower(),
                            )
                            grounded = SuggestModelResponse(
                                edits=[sort_edit, *grounded.edits],
                                explanation=grounded.explanation,
                                confidence=grounded.confidence,
                            )
                            edits_dicts = [edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits]
                            sorting_injected = True
                            logger.info("Sorting fallback triggered — injecting addSort edit.")
                        except Exception as exc:
                            logger.warning("Sorting fallback failed: %s", exc)
                    else:
                        logger.warning("Sorting implied but no column available for fallback.")

                if edits_have_aggregate(edits_dicts) and not edits_have_groupby(edits_dicts):
                    pruned_edits = [edit for edit in grounded.edits if getattr(edit, "op", "") != "addSelect"]
                    if len(pruned_edits) != len(grounded.edits):
                        grounded = SuggestModelResponse(
                            edits=pruned_edits,
                            explanation=grounded.explanation,
                            confidence=grounded.confidence,
                        )
                        edits_dicts = [edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits]
                        logger.info(
                            "AI suggest aggregation cleanup removed addSelect edits for aggregation-only result"
                        )

                listing_intent = prompt_implies_entity_listing(suggest_request.prompt)
                initial_select_count = count_add_select_edits(edits_dicts)
                identifier_projection_present = has_identifier_projection(edits_dicts)
                projection_completeness_fallback_injected = 0
                logger.info(
                    (
                        "AI suggest projection completeness signal attempt=%s listing_intent=%s "
                        "initial_select_count=%s has_identifier_projection=%s"
                    ),
                    attempt,
                    listing_intent,
                    initial_select_count,
                    identifier_projection_present,
                )
                if listing_intent and initial_select_count < 2:
                    if attempt == 1:
                        logger.warning(
                            "Projection completeness retry triggered: listing intent with fewer than two addSelect edits."
                        )
                        retry_reason = "missing_projection_completeness"
                        continue

                    identifier_candidates = get_identifier_candidates(candidate_column_dicts)
                    selected_identities = {
                        _column_ref_identity(edit.get("col") or {})
                        for edit in edits_dicts
                        if isinstance(edit, dict)
                        and str(edit.get("op") or "") == "addSelect"
                        and isinstance(edit.get("col"), dict)
                    }
                    injected_selects: list[AddSelectEdit] = []
                    for candidate in identifier_candidates:
                        if count_add_select_edits(edits_dicts) + len(injected_selects) >= 2:
                            break
                        if not isinstance(candidate, dict):
                            continue
                        col_dict = {
                            "modelColumnId": candidate.get("modelColumnId"),
                            "columnName": candidate.get("columnName"),
                            "workspaceTableId": candidate.get("workspaceTableId"),
                            "exprId": None,
                            "alias": None,
                        }
                        if not str(col_dict.get("columnName") or "").strip():
                            continue
                        identity = _column_ref_identity(col_dict)
                        if identity in selected_identities:
                            continue
                        try:
                            select_edit = AddSelectEdit(
                                op="addSelect",
                                col=SqlColumnKey.model_validate(col_dict),
                                alias=str(col_dict.get("columnName") or "").strip() or None,
                            )
                        except Exception:
                            continue
                        injected_selects.append(select_edit)
                        selected_identities.add(identity)
                    if injected_selects:
                        grounded = SuggestModelResponse(
                            edits=[*injected_selects, *grounded.edits],
                            explanation=grounded.explanation,
                            confidence=grounded.confidence,
                        )
                        edits_dicts = [edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits]
                        projection_completeness_fallback_injected = len(injected_selects)
                        logger.info("Projection completeness fallback triggered.")
                    logger.info(
                        "AI suggest projection completeness fallback injected_count=%s final_select_count=%s",
                        projection_completeness_fallback_injected,
                        count_add_select_edits(edits_dicts),
                    )

                reordered_edits = self._edit_enforcer.order_setdomain_first(grounded.edits)
                if reordered_edits != list(grounded.edits):
                    grounded = SuggestModelResponse(
                        edits=reordered_edits,
                        explanation=grounded.explanation,
                        confidence=grounded.confidence,
                    )
                    edits_dicts = [edit.model_dump(mode="json", exclude_none=False) for edit in grounded.edits]

                sqljson_seed = self._domain_seeder.seed_sqljson_domain_if_missing(
                    current_sqljson=suggest_request.currentSqlJson,
                    suggest_request=suggest_request,
                    validated=grounded,
                )
                sqljson = apply_edits(
                    sqljson_seed,
                    grounded.edits,
                    prompt=suggest_request.prompt,
                )
                self._edit_enforcer.enforce_sqljson_aggs_from_edits(sqljson, edits_dicts)
                self._edit_enforcer.enforce_sqljson_sorting_from_edits(sqljson, edits_dicts)
                if sqljson.get("domainId") is None and edits_reference_columns(edits_dicts):
                    post_inferred_domain = inferred_domain_id
                    if post_inferred_domain is None:
                        post_inferred_domain = self._domain_seeder.infer_domain_safely(
                            workspace_id=suggest_request.workspaceId,
                            edits=edits_dicts,
                        )
                    if post_inferred_domain is None:
                        post_inferred_domain = self._domain_seeder.fallback_domain_id(suggest_request)
                    if post_inferred_domain is not None:
                        sqljson["domainId"] = int(post_inferred_domain)
                        logger.info("Final domainId enforced=%s", sqljson["domainId"])
                    else:
                        logger.warning("Unable to determine domain.")
                        grounded = SuggestModelResponse(
                            edits=[],
                            explanation=(f"{grounded.explanation} Unable to determine domain for column edits.").strip(),
                            confidence=max(0.0, float(grounded.confidence) - 0.4),
                        )
                        edits_dicts = []
                        sqljson = apply_edits(
                            sqljson_seed,
                            grounded.edits,
                            prompt=suggest_request.prompt,
                        )

                if (
                    not isinstance(sqljson.get("aggs"), dict)
                    and not (sqljson.get("columns") or [])
                    and isinstance(sqljson.get("filters"), dict)
                ):
                    fallback_columns = self._domain_seeder.columns_from_filter_tree(sqljson.get("filters"))
                    if fallback_columns:
                        sqljson["columns"] = fallback_columns
                        logger.info(
                            "AI suggest sqlJson projection safety net populated columns=%s",
                            len(fallback_columns),
                        )

                filter_count = sum(1 for edit in grounded.edits if getattr(edit, "op", "") == "addFilter")
                final_edits = len(grounded.edits)
                final_select_count = count_add_select_edits(edits_dicts)
                final_columns_count = len(sqljson.get("columns") or [])
                logger.info(
                    (
                        "AI suggest edit stats attempt=%s final_edits=%s filter_edits=%s "
                        "literal_detected=%s final_domain_id=%s final_columns_count=%s "
                        "aggregation_intent=%s distinct_requested=%s has_aggregate=%s aggregation_fallback_injected=%s "
                        "geo_filter_expansion_count=%s "
                        "listing_intent=%s initial_select_count=%s final_select_count=%s projection_completeness_fallback_injected=%s "
                        "grouping_intent=%s has_groupby=%s grouping_fallback_injected=%s "
                        "sorting_intent=%s has_sorting=%s sorting_fallback_injected=%s "
                        "final_aggs_enabled=%s final_sorting_count=%s"
                    ),
                    attempt,
                    final_edits,
                    filter_count,
                    literal_detected,
                    sqljson.get("domainId"),
                    final_columns_count,
                    aggregation_intent,
                    distinct_requested,
                    edits_have_aggregate(edits_dicts),
                    aggregation_fallback_injected,
                    geo_filter_expansion_count,
                    listing_intent,
                    initial_select_count,
                    final_select_count,
                    projection_completeness_fallback_injected,
                    grouping_intent,
                    edits_have_groupby(edits_dicts),
                    grouping_injected_count,
                    sorting_intent,
                    edits_have_sorting(edits_dicts),
                    sorting_injected,
                    isinstance(sqljson.get("aggs"), dict),
                    len(sqljson.get("sorting") or []),
                )
                if literal_detected and filter_count == 0 and attempt == 1:
                    logger.warning("Missing required addFilter edits. Retrying with stricter instruction.")
                    retry_reason = "missing_filters"
                    fallback_response = SuggestAPIResponse(
                        edits=grounded.edits,
                        explanation=grounded.explanation,
                        confidence=grounded.confidence,
                        sqlJson=sqljson,
                        debug={"model": self.model, "attempts": 2},
                    )
                    continue
                if literal_detected and filter_count == 0 and attempt == 2:
                    logger.error("AI suggest retry still missing addFilter edits for literal prompt")

                latency_ms = int((time.perf_counter() - start) * 1000)
                logger.info(
                    (
                        "AI suggest completed model=%s attempts=%s llm_latency_ms=%s "
                        "invalid_edits_removed=%s normalized_key_rewrites=%s normalized_edits_dropped=%s "
                        "final_edits=%s filter_edits=%s"
                    ),
                    self.model,
                    attempt,
                    latency_ms,
                    removed_count,
                    normalization_meta.get("rewritten_ops", 0),
                    normalization_meta.get("dropped_edits", 0),
                    final_edits,
                    filter_count,
                )
                return SuggestAPIResponse(
                    edits=grounded.edits,
                    explanation=grounded.explanation,
                    confidence=grounded.confidence,
                    sqlJson=sqljson,
                    debug={"model": self.model, "attempts": attempt},
                )
            except ValidationError as exc:
                last_error = {
                    "attempt": attempt,
                    "type": "schema_validation_error",
                    "message": "Model output did not match required schema",
                    "errors": exc.errors(include_url=False),
                    "content": content,
                }
                logger.warning("AI suggest schema validation failed on attempt %s: %s", attempt, exc)
                retry_reason = "repair"
                if attempt == 2 and fallback_response is not None:
                    logger.error(
                        "AI suggest retry returned invalid schema; returning first valid response without filters"
                    )
                    return fallback_response

        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.error(
            "AI suggest failed model=%s attempts=2 llm_latency_ms=%s details=%s",
            self.model,
            latency_ms,
            last_error,
        )
        raise InvalidModelResponseError(last_error or {"type": "unknown_error"})

    def health(self) -> Dict[str, Any]:
        return self._vllm_client.health()


__all__ = ["AISuggestService", "InvalidModelResponseError"]
