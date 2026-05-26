from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Dict, Mapping, Optional, Tuple

from app.adapters.mysql_sql_executor import ForgeMetaSQL
from app.exceptions.forge_error import ForgeError
from app.models.domain.domain_profile import DomainProfileBase, _build_embedding_text, compute_content_hash
from app.ports.sql_executor import ForgeQueryPort
from app.repositories.feedback_learning import (
    CatalogPromotionAuditRepository,
    DomainOverrideRepository,
    SemanticOverrideRepository,
)
from app.services.planner.semantic_retrieval_helpers import domain_key_from_name


class CatalogPromotionService:
    def __init__(
        self,
        *,
        sql: Optional[ForgeQueryPort] = None,
        semantic_override_repository: Optional[SemanticOverrideRepository] = None,
        domain_override_repository: Optional[DomainOverrideRepository] = None,
        audit_repository: Optional[CatalogPromotionAuditRepository] = None,
    ) -> None:
        self._sql = sql or ForgeMetaSQL()
        self._semantic_override_repository = (
            semantic_override_repository or SemanticOverrideRepository(sql=self._sql)
        )
        self._domain_override_repository = (
            domain_override_repository or DomainOverrideRepository(sql=self._sql)
        )
        self._audit_repository = (
            audit_repository or CatalogPromotionAuditRepository(sql=self._sql)
        )

    def promote_semantic_override(
        self,
        *,
        override_id: int,
        promoted_by: str,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        override = self._load_active_semantic_override(override_id=override_id)
        target_table, target_record_key, promotion_action = _semantic_audit_target(override)
        try:
            with self._sql.transaction() as tx:
                self._apply_semantic_override(tx=tx, override=override)
                _audit_repository(self._audit_repository, tx=tx).create_audit(
                    payload=_audit_payload(
                        source_type="semantic_override",
                        source_id=override_id,
                        target_table=target_table,
                        target_record_key=target_record_key,
                        promotion_action=promotion_action,
                        promotion_status="succeeded",
                        promoted_by=promoted_by,
                        notes=notes,
                        error_message=None,
                        retry_count=0,
                        last_retry_at=None,
                    )
                )
                _semantic_override_repository(self._semantic_override_repository, tx=tx).deactivate(
                    override_id=override_id
                )
            return {
                "override_id": int(override_id),
                "promotion_status": "succeeded",
                "target_table": target_table,
                "target_record_key": target_record_key,
            }
        except Exception as exc:
            self._record_failed_audit(
                source_type="semantic_override",
                source_id=override_id,
                target_table=target_table,
                target_record_key=target_record_key,
                promotion_action=promotion_action,
                promoted_by=promoted_by,
                notes=notes,
                error_message=str(exc),
            )
            raise

    def promote_domain_override(
        self,
        *,
        override_id: int,
        promoted_by: str,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        override = self._load_active_domain_override(override_id=override_id)
        target_table, target_record_key, promotion_action = _domain_audit_target(override)
        try:
            with self._sql.transaction() as tx:
                self._apply_domain_override(tx=tx, override=override)
                _audit_repository(self._audit_repository, tx=tx).create_audit(
                    payload=_audit_payload(
                        source_type="domain_override",
                        source_id=override_id,
                        target_table=target_table,
                        target_record_key=target_record_key,
                        promotion_action=promotion_action,
                        promotion_status="succeeded",
                        promoted_by=promoted_by,
                        notes=notes,
                        error_message=None,
                        retry_count=0,
                        last_retry_at=None,
                    )
                )
                _domain_override_repository(self._domain_override_repository, tx=tx).deactivate(
                    override_id=override_id
                )
            return {
                "override_id": int(override_id),
                "promotion_status": "succeeded",
                "target_table": target_table,
                "target_record_key": target_record_key,
            }
        except Exception as exc:
            self._record_failed_audit(
                source_type="domain_override",
                source_id=override_id,
                target_table=target_table,
                target_record_key=target_record_key,
                promotion_action=promotion_action,
                promoted_by=promoted_by,
                notes=notes,
                error_message=str(exc),
            )
            raise

    def _load_active_semantic_override(self, *, override_id: int) -> Dict[str, Any]:
        row = self._semantic_override_repository.get_by_id(override_id=int(override_id))
        if row is None:
            raise ForgeError("Semantic override not found", status_code=404)
        if str(row.get("status") or "").strip().lower() != "active":
            raise ForgeError("Semantic override is not active", status_code=409)
        return row

    def _load_active_domain_override(self, *, override_id: int) -> Dict[str, Any]:
        row = self._domain_override_repository.get_by_id(override_id=int(override_id))
        if row is None:
            raise ForgeError("Domain override not found", status_code=404)
        if str(row.get("status") or "").strip().lower() != "active":
            raise ForgeError("Domain override is not active", status_code=409)
        return row

    def _apply_semantic_override(self, *, tx: ForgeQueryPort, override: Mapping[str, Any]) -> None:
        override_type = _text(override.get("override_type")).lower()
        if override_type == "add_alias":
            self._promote_alias(tx=tx, override=override)
            return
        if override_type in {"concept_rank_boost", "concept_rank_penalty"}:
            self._promote_concept_priority(tx=tx, override=override)
            return
        if override_type in {
            "add_phrase_hint",
            "add_ambiguity_note",
            "add_domain_lexical_hint",
            "add_domain_example_prompt",
        }:
            self._promote_domain_profile_note(tx=tx, override=override)
            return
        raise NotImplementedError(f"Unsupported semantic override promotion type: {override_type}")

    def _apply_domain_override(self, *, tx: ForgeQueryPort, override: Mapping[str, Any]) -> None:
        override_type = _text(override.get("override_type")).lower()
        if override_type in {
            "add_domain_example_prompt",
            "add_domain_lexical_hint",
            "add_ambiguity_note",
            "add_phrase_hint",
        }:
            self._promote_domain_profile_note(tx=tx, override=override)
            return
        raise NotImplementedError(f"Unsupported domain override promotion type: {override_type}")

    def _promote_alias(self, *, tx: ForgeQueryPort, override: Mapping[str, Any]) -> None:
        payload = _payload_json(override)
        alias_key = _text(payload.get("alias_key") or payload.get("alias"))
        match_kind = _text(payload.get("match_kind") or "exact").lower() or "exact"
        concept_key = _text(override.get("concept_key")).upper()
        if alias_key == "" or concept_key == "":
            raise ForgeError("Alias override payload is malformed", status_code=400)

        existing = tx.execute_query_mappings(
            """
            SELECT id, concept_key, weight
            FROM semantic_concept_alias
            WHERE alias_key = :alias_key
              AND match_kind = :match_kind
            LIMIT 1
            """,
            {"alias_key": alias_key, "match_kind": match_kind},
        )
        weight = _to_float(payload.get("weight"), default=1.0)
        if existing:
            row = dict(existing[0])
            existing_concept_key = _text(row.get("concept_key")).upper()
            if existing_concept_key != concept_key:
                raise ForgeError(
                    "Alias already belongs to a different concept",
                    status_code=409,
                    details={"alias_key": alias_key, "match_kind": match_kind},
                )
            tx.execute_write(
                """
                UPDATE semantic_concept_alias
                SET weight = :weight
                WHERE id = :id
                """,
                {
                    "id": int(row.get("id") or 0),
                    "weight": max(weight, _to_float(row.get("weight"), default=0.0)),
                },
            )
            return

        tx.execute_insert(
            """
            INSERT INTO semantic_concept_alias (
              alias_key,
              concept_key,
              match_kind,
              weight
            ) VALUES (
              :alias_key,
              :concept_key,
              :match_kind,
              :weight
            )
            """,
            {
                "alias_key": alias_key,
                "concept_key": concept_key,
                "match_kind": match_kind,
                "weight": weight,
            },
        )

    def _promote_concept_priority(self, *, tx: ForgeQueryPort, override: Mapping[str, Any]) -> None:
        payload = _payload_json(override)
        delta = max(1, int(round(_to_float(payload.get("delta", payload.get("score_delta", payload.get("weight"))), default=0.0))))
        concept_key = _text(override.get("concept_key")).upper()
        override_type = _text(override.get("override_type")).lower()
        if concept_key == "":
            raise ForgeError("Concept override payload is malformed", status_code=400)

        if override_type == "concept_rank_boost":
            sql = """
                UPDATE semantic_concept
                SET display_priority = display_priority + :delta
                WHERE concept_key = :concept_key
            """
        else:
            sql = """
                UPDATE semantic_concept
                SET display_priority = GREATEST(0, display_priority - :delta)
                WHERE concept_key = :concept_key
            """
        affected = tx.execute_write(
            sql,
            {"concept_key": concept_key, "delta": delta},
        )
        if int(affected or 0) <= 0:
            raise ForgeError("Semantic concept not found", status_code=404)

    def _promote_domain_profile_note(self, *, tx: ForgeQueryPort, override: Mapping[str, Any]) -> None:
        workspace_id = _optional_text(override.get("workspace_id"))
        if workspace_id is None:
            raise ForgeError(
                "Global domain-profile overrides are runtime-only and may not be promoted",
                status_code=400,
            )

        override_type = _text(override.get("override_type")).lower()
        payload = _payload_json(override)
        domain_key = _resolve_override_domain_key(override)
        if domain_key is None:
            raise ForgeError("Domain override payload is malformed", status_code=400)
        note_value = _override_note_value(override_type=override_type, payload=payload)
        if note_value is None:
            raise ForgeError("Domain note override payload is malformed", status_code=400)

        domain_row = _resolve_domain_row(tx=tx, workspace_id=workspace_id, domain_key=domain_key)
        domain_id = int(domain_row["id"])
        existing_rows = tx.execute_query_mappings(
            """
            SELECT summary, keywords, entities, metrics, attributes, synonyms, acronyms, notes
            FROM domain_profile
            WHERE workspace_id = :workspace_id
              AND domain_id = :domain_id
            LIMIT 1
            """,
            {"workspace_id": workspace_id, "domain_id": domain_id},
        )
        current = dict(existing_rows[0]) if existing_rows else {}
        tag = f"[feedback_learning:{override_type}]"
        note_line = f"{tag} {note_value}".strip()
        merged_notes = _merge_note_text(current.get("notes"), note_line)
        profile_base = DomainProfileBase(
            summary=_optional_text(current.get("summary")),
            keywords=_parse_json_like(current.get("keywords")),
            entities=_parse_json_like(current.get("entities")),
            metrics=_parse_json_like(current.get("metrics")),
            attributes=_parse_json_like(current.get("attributes")),
            synonyms=_parse_json_like(current.get("synonyms")),
            acronyms=_parse_json_like(current.get("acronyms")),
            notes=merged_notes,
        )
        embedding_text = _build_embedding_text(profile_base)
        content_hash = compute_content_hash(embedding_text)

        params = {
            "workspace_id": workspace_id,
            "domain_id": domain_id,
            "summary": _optional_text(current.get("summary")),
            "keywords": _json_or_none(_parse_json_like(current.get("keywords"))),
            "entities": _json_or_none(_parse_json_like(current.get("entities"))),
            "metrics": _json_or_none(_parse_json_like(current.get("metrics"))),
            "attributes": _json_or_none(_parse_json_like(current.get("attributes"))),
            "synonyms": _json_or_none(_parse_json_like(current.get("synonyms"))),
            "acronyms": _json_or_none(_parse_json_like(current.get("acronyms"))),
            "notes": merged_notes,
            "embedding_text": embedding_text,
            "content_hash": content_hash,
        }
        if existing_rows:
            tx.execute_write(
                """
                UPDATE domain_profile
                SET notes = :notes,
                    embedding_text = :embedding_text,
                    content_hash = :content_hash
                WHERE workspace_id = :workspace_id
                  AND domain_id = :domain_id
                """,
                {
                    "workspace_id": workspace_id,
                    "domain_id": domain_id,
                    "notes": merged_notes,
                    "embedding_text": embedding_text,
                    "content_hash": content_hash,
                },
            )
            return

        tx.execute_insert(
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

    def _record_failed_audit(
        self,
        *,
        source_type: str,
        source_id: int,
        target_table: str,
        target_record_key: str,
        promotion_action: str,
        promoted_by: str,
        notes: Optional[str],
        error_message: str,
    ) -> None:
        latest = self._audit_repository.get_latest_by_source(
            source_type=source_type,
            source_id=int(source_id),
            promotion_action=promotion_action,
            target_table=target_table,
        )
        if latest is not None and _text(latest.get("promotion_status")).lower() == "failed":
            self._audit_repository.update_failure(
                audit_id=int(latest["id"]),
                retry_count=int(latest.get("retry_count") or 0) + 1,
                last_retry_at=_utcnow(),
                error_message=error_message,
            )
            return
        self._audit_repository.create_audit(
            payload=_audit_payload(
                source_type=source_type,
                source_id=source_id,
                target_table=target_table,
                target_record_key=target_record_key,
                promotion_action=promotion_action,
                promotion_status="failed",
                promoted_by=promoted_by,
                notes=notes,
                error_message=error_message,
                retry_count=0,
                last_retry_at=None,
            )
        )


def _semantic_audit_target(override: Mapping[str, Any]) -> Tuple[str, str, str]:
    override_type = _text(override.get("override_type")).lower()
    payload = _payload_json(override)
    if override_type == "add_alias":
        alias_key = _text(payload.get("alias_key") or payload.get("alias"))
        return (
            "semantic_concept_alias",
            f"{_text(override.get('concept_key')).upper()}:{alias_key}",
            "upsert_alias",
        )
    if override_type in {"concept_rank_boost", "concept_rank_penalty"}:
        return ("semantic_concept", _text(override.get("concept_key")).upper(), "update_priority")
    return (
        "domain_profile",
        _domain_profile_record_key(
            workspace_id=_optional_text(override.get("workspace_id")),
            domain_key=_resolve_override_domain_key(override),
        ),
        "append_domain_profile_note",
    )


def _domain_audit_target(override: Mapping[str, Any]) -> Tuple[str, str, str]:
    return (
        "domain_profile",
        _domain_profile_record_key(
            workspace_id=_optional_text(override.get("workspace_id")),
            domain_key=_optional_text(override.get("domain_key")),
        ),
        "append_domain_profile_note",
    )


def _domain_profile_record_key(*, workspace_id: Optional[str], domain_key: Optional[str]) -> str:
    return f"{workspace_id or '__global__'}:{domain_key or 'unknown'}"


def _resolve_override_domain_key(override: Mapping[str, Any]) -> Optional[str]:
    payload = _payload_json(override)
    return _optional_text(override.get("domain_key") or payload.get("domain_key"))


def _override_note_value(*, override_type: str, payload: Mapping[str, Any]) -> Optional[str]:
    if override_type == "add_domain_example_prompt":
        return _optional_text(payload.get("prompt") or payload.get("value"))
    if override_type == "add_domain_lexical_hint":
        return _optional_text(payload.get("hint") or payload.get("phrase") or payload.get("value"))
    if override_type == "add_ambiguity_note":
        return _optional_text(payload.get("note") or payload.get("value"))
    if override_type == "add_phrase_hint":
        return _optional_text(payload.get("phrase") or payload.get("hint") or payload.get("value"))
    return None


def _resolve_domain_row(
    *,
    tx: ForgeQueryPort,
    workspace_id: str,
    domain_key: str,
) -> Dict[str, Any]:
    rows = tx.execute_query_mappings(
        """
        SELECT id, name
        FROM domain
        WHERE workspace_id = :workspace_id
          AND is_active = 1
        ORDER BY id ASC
        """,
        {"workspace_id": workspace_id},
    )
    target_key = _text(domain_key).upper()
    for row in rows:
        if domain_key_from_name(row.get("name"), int(row.get("id") or 0)) == target_key:
            return dict(row)
    raise ForgeError(
        "Domain not found for override promotion",
        status_code=404,
        details={"workspace_id": workspace_id, "domain_key": target_key},
    )


def _audit_payload(
    *,
    source_type: str,
    source_id: int,
    target_table: str,
    target_record_key: str,
    promotion_action: str,
    promotion_status: str,
    promoted_by: str,
    notes: Optional[str],
    error_message: Optional[str],
    retry_count: int,
    last_retry_at: Optional[datetime],
) -> Dict[str, Any]:
    return {
        "source_type": source_type,
        "source_id": int(source_id),
        "target_table": target_table,
        "target_record_key": target_record_key,
        "promotion_action": promotion_action,
        "promotion_status": promotion_status,
        "promoted_by": promoted_by,
        "promoted_at": _utcnow(),
        "retry_count": int(retry_count),
        "last_retry_at": last_retry_at,
        "notes": _optional_text(notes),
        "error_message": _optional_text(error_message),
    }


def _payload_json(row: Mapping[str, Any]) -> Dict[str, Any]:
    payload = row.get("override_value_json")
    return dict(payload) if isinstance(payload, Mapping) else {}


def _parse_json_like(value: Any) -> Any:
    if value is None or isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    return value


def _json_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _merge_note_text(existing: Any, note_line: str) -> str:
    current = _text(existing)
    if current == "":
        return note_line
    lines = [line.strip() for line in current.splitlines() if line.strip()]
    if note_line not in lines:
        lines.append(note_line)
    return "\n".join(lines)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> Optional[str]:
    text = _text(value)
    return text or None


def _to_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _audit_repository(repository: CatalogPromotionAuditRepository, *, tx: ForgeQueryPort):
    if type(repository) is CatalogPromotionAuditRepository:
        return CatalogPromotionAuditRepository(sql=tx)
    return repository


def _semantic_override_repository(repository: SemanticOverrideRepository, *, tx: ForgeQueryPort):
    if type(repository) is SemanticOverrideRepository:
        return SemanticOverrideRepository(sql=tx)
    return repository


def _domain_override_repository(repository: DomainOverrideRepository, *, tx: ForgeQueryPort):
    if type(repository) is DomainOverrideRepository:
        return DomainOverrideRepository(sql=tx)
    return repository


__all__ = ["CatalogPromotionService"]
