from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from pydantic import ValidationError

from app.config.llm_resolver import build_llm_client_for_role
from app.constants.llm_roles import LLMRole
from app.services.llm.llm_client import LLMClient
from app.services.semantic.semantic_llm_schema import BatchOutput, normalize_concept_key

SYSTEM_PROMPT = """You are a strict semantic classification engine for database columns.

Return valid JSON only.
No markdown.
No comments.
No prose.
No extra keys.

OUTPUT CONTRACT
- Return exactly one top-level JSON object.
- Top-level object must contain exactly one key: items.
- items must be an array.
- items length must exactly match input card count.
- Preserve order: output item i maps to input card i.

Each item must include ALL required fields:
concept_key, concept_source, canonical_match_confidence, semantic_type, sub_type, entity, granularity_rank, filter_allowed, group_by_allowed, aggregation_allowed, is_identifier, is_metric, display_priority, sensitive, confidence, reasons.

Field requirements:
- concept_key: non-empty string, UPPER_SNAKE_CASE, no dots, no slashes.
- concept_source: canonical or fallback.
- canonical_match_confidence: float 0.0..1.0.
- semantic_type: one of entity, identifier, attribute, geography, time, metric, flag, reference, other.
- sub_type: string or null.
- entity: string or null.
- granularity_rank: integer.
- filter_allowed: boolean.
- group_by_allowed: boolean.
- aggregation_allowed: boolean.
- is_identifier: boolean.
- is_metric: boolean.
- display_priority: integer.
- sensitive: boolean.
- confidence: float 0.0..1.0.
- reasons: array of 1-3 concise evidence-based strings.

Canonical concept behavior:
- Prefer concept_key from KNOWN_CONCEPTS when there is a strong match.
- If you choose canonical, set concept_source to canonical.
- If no canonical concept fits, set concept_source to fallback and use normalized columnName as concept_key.
- Never output table.column concept keys.

Defaults when uncertain:
- concept_source: fallback
- canonical_match_confidence: 0.0
- semantic_type: attribute
- sub_type: null
- entity: null
- granularity_rank: 0
- filter_allowed: true
- group_by_allowed: true
- aggregation_allowed: false
- is_identifier: false
- is_metric: false
- display_priority: 0
- sensitive: false
- confidence: 0.5
- reasons: [\"defaulted_due_to_uncertainty\"]
"""

USER_TEMPLATE = """Classify this batch of database column cards for semantic registry output.

Vertical context:
[[VERTICAL_OR_GENERIC]]

Known canonical concepts JSON array:
[[KNOWN_CONCEPTS_JSON]]

Instructions:
- Produce exactly one top-level JSON object with key \"items\".
- items length and order must exactly match the input cards.
- Include every required field on every item.
- Use concept_source=canonical only when concept_key is from KNOWN_CONCEPTS.
- Use concept_source=fallback when no canonical concept matches.
- Return JSON only.

Input column cards JSON array:
[[CARDS_JSON]]
"""


class SemanticLLMLabeler:
    def __init__(self, *, llm_client: Optional[LLMClient] = None) -> None:
        self._explicit_llm = llm_client is not None
        self._llm = llm_client or LLMClient()
        self._llm_runtime_meta: Dict[str, Any] = {
            "source": "bootstrap",
            "role": LLMRole.ENRICHMENT,
            "llm_id": None,
            "provider": "generic",
            "model": str(getattr(self._llm, "_model", "") or ""),
            "endpoint": str(getattr(self._llm, "_endpoint", "") or ""),
        }
        self.last_batch_raw: List[Dict[str, Any]] = []
        self._max_prompt_chars = 24000
        self._max_known_concepts = 120

    def label_cards(
        self,
        *,
        cards: List[Dict[str, Any]],
        vertical: Optional[str],
        known_concepts: Optional[List[Dict[str, Any]]] = None,
        workspace_id: Optional[str] = None,
        llm_id: Optional[int] = None,
    ) -> Tuple[List[Optional[Dict[str, Any]]], List[Optional[str]]]:
        self.last_batch_raw = []
        if not cards:
            return [], []
        ws = str(workspace_id or "").strip()
        if ws and not self._explicit_llm:
            resolved = build_llm_client_for_role(
                workspace_id=ws,
                role=LLMRole.ENRICHMENT,
                llm_id_override=llm_id,
                timeout_seconds=None,
            )
            self._llm = resolved.client
            self._llm_runtime_meta = {
                "source": resolved.source,
                "role": resolved.role,
                "llm_id": resolved.llm_id,
                "provider": resolved.provider,
                "model": resolved.model,
                "endpoint": resolved.endpoint,
            }

        slim_cards = [self._slim_card(card) for card in cards]
        canonical = self._select_known_concepts(known_concepts or [], slim_cards)
        known_keys = self._known_keys(canonical)
        outputs, errors, raws = self._label_cards_recursive(
            cards=slim_cards,
            vertical=vertical,
            canonical=canonical,
            known_keys=known_keys,
        )
        self.last_batch_raw = raws
        return outputs, errors

    def _label_cards_recursive(
        self,
        *,
        cards: List[Dict[str, Any]],
        vertical: Optional[str],
        canonical: List[Dict[str, Any]],
        known_keys: List[str],
    ) -> Tuple[List[Optional[Dict[str, Any]]], List[Optional[str]], List[Dict[str, Any]]]:
        if not cards:
            return [], [], []
        base_user_prompt = (
            USER_TEMPLATE.replace("[[VERTICAL_OR_GENERIC]]", (vertical or "generic"))
            .replace("[[KNOWN_CONCEPTS_JSON]]", json.dumps(canonical, ensure_ascii=True))
            .replace("[[CARDS_JSON]]", json.dumps(cards, ensure_ascii=True))
        )

        if len(base_user_prompt) + len(SYSTEM_PROMPT) > self._max_prompt_chars and len(cards) > 1:
            return self._split_and_recurse(cards=cards, vertical=vertical, canonical=canonical, known_keys=known_keys)

        attempt1 = self._call_with_trace(system_prompt=SYSTEM_PROMPT, user_prompt=base_user_prompt)
        parsed, error = self._validate_trace(
            attempt1,
            expected_len=len(cards),
            known_concept_keys=known_keys,
        )
        if parsed is not None:
            raw_payload = {"attempt1": self._trace_for_storage(attempt1)}
            return parsed, [None] * len(cards), [raw_payload for _ in cards]

        if self._is_context_limit_error(attempt1):
            if len(cards) > 1:
                return self._split_and_recurse(cards=cards, vertical=vertical, canonical=canonical, known_keys=known_keys)
            reduced_canonical = canonical[: min(25, len(canonical))]
            reduced_prompt = (
                USER_TEMPLATE.replace("[[VERTICAL_OR_GENERIC]]", (vertical or "generic"))
                .replace("[[KNOWN_CONCEPTS_JSON]]", json.dumps(reduced_canonical, ensure_ascii=True))
                .replace("[[CARDS_JSON]]", json.dumps([self._slim_card(cards[0], aggressive=True)], ensure_ascii=True))
            )
            attempt1 = self._call_with_trace(system_prompt=SYSTEM_PROMPT, user_prompt=reduced_prompt)
            parsed, error = self._validate_trace(
                attempt1,
                expected_len=1,
                known_concept_keys=self._known_keys(reduced_canonical),
            )
            if parsed is not None:
                raw_payload = {"attempt1": self._trace_for_storage(attempt1)}
                return parsed, [None], [raw_payload]

        strict_fix_prompt = (
            f"{base_user_prompt}\n\n"
            "STRICT FIXUP:\n"
            "- Allowed semantic_type enums: entity, identifier, attribute, geography, time, metric, flag, reference, other.\n"
            "- Allowed concept_source enums: canonical, fallback.\n"
            "- Include every required key on each item.\n"
            "- Example valid single item:\n"
            '{"concept_key":"SCHOOL_ID","concept_source":"canonical","canonical_match_confidence":0.9,'
            '"semantic_type":"identifier","sub_type":null,"entity":"school","granularity_rank":0,'
            '"filter_allowed":true,"group_by_allowed":true,"aggregation_allowed":false,"is_identifier":true,'
            '"is_metric":false,"display_priority":0,"sensitive":false,"confidence":0.9,'
            '"reasons":["column_name_evidence"]}\n'
            f"Previous invalid output (truncated): {str(attempt1.get('content') or attempt1.get('raw_text') or '')[:3000]}\n"
            "Return JSON only, with top-level {items:[...]} and NO extra keys."
        )

        attempt2 = self._call_with_trace(system_prompt=SYSTEM_PROMPT, user_prompt=strict_fix_prompt)
        parsed_retry, error_retry = self._validate_trace(
            attempt2,
            expected_len=len(cards),
            known_concept_keys=known_keys,
        )
        if parsed_retry is not None:
            raw_payload = {
                "attempt1": self._trace_for_storage(attempt1),
                "attempt2": self._trace_for_storage(attempt2),
            }
            return parsed_retry, [None] * len(cards), [raw_payload for _ in cards]

        if self._is_context_limit_error(attempt2) and len(cards) > 1:
            return self._split_and_recurse(cards=cards, vertical=vertical, canonical=canonical, known_keys=known_keys)

        failure = error_retry or error or "schema_validation_error:invalid_output"
        raw_payload = {
            "attempt1": self._trace_for_storage(attempt1, failure if error is None else error),
            "attempt2": self._trace_for_storage(attempt2, failure if error_retry is None else error_retry),
        }
        return [None] * len(cards), [failure] * len(cards), [raw_payload for _ in cards]

    def _split_and_recurse(
        self,
        *,
        cards: List[Dict[str, Any]],
        vertical: Optional[str],
        canonical: List[Dict[str, Any]],
        known_keys: List[str],
    ) -> Tuple[List[Optional[Dict[str, Any]]], List[Optional[str]], List[Dict[str, Any]]]:
        if len(cards) <= 1:
            failure = "schema_validation_error:context_limit"
            raw_payload = {
                "attempt1": {
                    "raw_text": "",
                    "parsed": None,
                    "error": failure,
                }
            }
            return [None], [failure], [raw_payload]

        mid = len(cards) // 2
        left_cards = cards[:mid]
        right_cards = cards[mid:]
        left_out, left_err, left_raw = self._label_cards_recursive(
            cards=left_cards,
            vertical=vertical,
            canonical=canonical,
            known_keys=known_keys,
        )
        right_out, right_err, right_raw = self._label_cards_recursive(
            cards=right_cards,
            vertical=vertical,
            canonical=canonical,
            known_keys=known_keys,
        )
        return left_out + right_out, left_err + right_err, left_raw + right_raw

    def _call_with_trace(self, *, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        try:
            if hasattr(self._llm, "chat_json_with_trace"):
                trace = self._llm.chat_json_with_trace(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_format=True,
                )
                if isinstance(trace, dict):
                    return trace
            parsed = self._llm.chat_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_format=True,
                retry_invalid_schema=False,
                validator=lambda body: isinstance(body.get("items"), list),
            )
            return {
                "raw_text": json.dumps(parsed, ensure_ascii=True),
                "parsed": parsed,
                "content": json.dumps(parsed, ensure_ascii=True),
                "error": None,
            }
        except Exception as exc:
            return {
                "raw_text": "",
                "parsed": None,
                "content": None,
                "error": f"llm_call_error:{str(exc)}",
            }

    def _validate_trace(
        self,
        trace: Dict[str, Any],
        *,
        expected_len: int,
        known_concept_keys: List[str],
    ) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        parsed = trace.get("parsed")
        if not isinstance(parsed, dict):
            content = trace.get("content")
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                except Exception:
                    return None, "schema_validation_error:json_parse_error"
        if not isinstance(parsed, dict):
            return None, "schema_validation_error:missing"
        return self._validate_output(parsed, expected_len=expected_len, known_concept_keys=known_concept_keys)

    @staticmethod
    def _validate_output(
        raw: Dict[str, Any],
        *,
        expected_len: int,
        known_concept_keys: List[str],
    ) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        try:
            model = BatchOutput.model_validate(raw, context={"known_concept_keys": known_concept_keys})
        except ValidationError as exc:
            detail = exc.errors()[0]
            return None, f"schema_validation_error:{detail.get('type', 'unknown')}"
        except Exception as exc:
            return None, f"schema_validation_error:{str(exc)}"

        items = [item.model_dump(mode="json") for item in model.items]
        if len(items) != expected_len:
            return None, f"schema_validation_error:length_mismatch:{len(items)}:{expected_len}"
        return items, None

    @staticmethod
    def _trace_for_storage(trace: Dict[str, Any], error: Optional[str] = None) -> Dict[str, Any]:
        out = {
            "raw_text": trace.get("raw_text") if isinstance(trace.get("raw_text"), str) else "",
            "parsed": trace.get("parsed") if isinstance(trace.get("parsed"), dict) else None,
            "error": error or (trace.get("error") if isinstance(trace.get("error"), str) else None),
        }
        return out

    @staticmethod
    def _known_keys(canonical: List[Dict[str, Any]]) -> List[str]:
        return sorted(
            {
                normalize_concept_key(str(item.get("concept_key") or ""))
                for item in canonical
                if normalize_concept_key(str(item.get("concept_key") or ""))
            }
        )

    def _select_known_concepts(self, canonical: List[Dict[str, Any]], cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not canonical:
            return []

        card_tokens = set()
        for card in cards:
            for text_val in (
                str(card.get("columnName") or ""),
                str(card.get("description") or ""),
                str(card.get("tableName") or ""),
            ):
                for tok in self._tokenize(text_val):
                    card_tokens.add(tok)

        scored: List[Tuple[int, Dict[str, Any]]] = []
        for concept in canonical:
            key = normalize_concept_key(str(concept.get("concept_key") or ""))
            if not key:
                continue
            mini = {
                "concept_key": key,
                "semantic_type": concept.get("semantic_type"),
                "sub_type": concept.get("sub_type"),
                "entity": concept.get("entity"),
            }
            concept_tokens = set(self._tokenize(key))
            score = len(card_tokens & concept_tokens)
            scored.append((score, mini))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [item for _, item in scored[: self._max_known_concepts]]
        if not top:
            top = [
                {
                    "concept_key": normalize_concept_key(str(c.get("concept_key") or "")),
                    "semantic_type": c.get("semantic_type"),
                    "sub_type": c.get("sub_type"),
                    "entity": c.get("entity"),
                }
                for c in canonical[: self._max_known_concepts]
                if normalize_concept_key(str(c.get("concept_key") or ""))
            ]
        return top

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        norm = "".join(ch if ch.isalnum() else " " for ch in text.lower())
        return [tok for tok in norm.split() if tok]

    @staticmethod
    def _slim_card(card: Dict[str, Any], aggressive: bool = False) -> Dict[str, Any]:
        out = dict(card or {})
        desc_limit = 120 if aggressive else 280
        sample_limit = 3 if aggressive else 8
        sample_len = 40 if aggressive else 80
        description = out.get("description")
        if description is not None:
            out["description"] = str(description)[:desc_limit]
        samples = out.get("samples")
        if isinstance(samples, list):
            slim_samples = []
            for sample in samples[:sample_limit]:
                if sample is None:
                    continue
                slim_samples.append(str(sample)[:sample_len])
            out["samples"] = slim_samples
        return out

    @staticmethod
    def _is_context_limit_error(trace: Dict[str, Any]) -> bool:
        parsed = trace.get("parsed")
        if isinstance(parsed, dict):
            err = parsed.get("error")
            if isinstance(err, dict):
                msg = str(err.get("message") or "").lower()
                param = str(err.get("param") or "").lower()
                if "maximum context length" in msg or param == "input_tokens":
                    return True
        raw_text = str(trace.get("raw_text") or "").lower()
        if "maximum context length" in raw_text or "input_tokens" in raw_text:
            return True
        return False
