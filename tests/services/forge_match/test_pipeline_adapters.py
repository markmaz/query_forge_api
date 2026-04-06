from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.forge_match.field_extractor import SourceFieldRecord
from app.services.forge_match.pipeline_adapters import (
    ForgeMatchPersistenceAdapter,
    ForgeMatchSessionExecutionAdapter,
    _parse_json_dict,
)
from app.services.forge_match.session_pipeline_artifacts import ForgeMatchSessionWorkArtifact
from app.services.shared_ai.artifacts import MatchOutcomeArtifact
from app.services.shared_ai.context import PipelineContext


def _context(**request_overrides) -> PipelineContext:
    request = {
        "session_id": "sess-1",
        "source_record_id": 10,
        "top_n": 8,
        "vertical_norm": "education",
        **request_overrides,
    }
    return PipelineContext(
        pipeline_name="forge_match_row_pipeline",
        trace_id="trace-1",
        workspace_id="ws-1",
        user_id=None,
        vertical_norm="education",
        request=request,
    )


def _source_row(row_id: str = "Sheet1:2", source_id: int = 10) -> dict[str, object]:
    return {
        "id": source_id,
        "row_id": row_id,
        "sheet_name": "Sheet1",
        "row_number": 2,
        "source_field_name": "BirthDate",
        "source_description": "Student date of birth",
        "source_type": "date",
        "source_object_name": "StudentDemographics",
        "sample_value": "2010-02-14",
        "category": None,
        "normalized_search_text": "BirthDate. Student date of birth",
        "raw_row_json": '{"field":"BirthDate"}',
    }


def test_persistence_adapter_rejects_non_integer_source_record_id() -> None:
    persisted: list[dict[str, object]] = []
    adapter = ForgeMatchPersistenceAdapter(persist_result=lambda **kwargs: persisted.append(kwargs))

    with pytest.raises(TypeError, match="requires integer source_record_id"):
        adapter.persist(
            context=_context(source_record_id="bad-id"),
            outcome=MatchOutcomeArtifact(selected_candidate=None),
        )

    assert persisted == []


def test_session_execution_adapter_persists_failure_for_expected_runtime_errors() -> None:
    failures: list[dict[str, object]] = []
    progress: list[dict[str, object]] = []

    adapter = ForgeMatchSessionExecutionAdapter(
        is_cancel_requested=lambda **_kwargs: False,
        update_progress=lambda **kwargs: progress.append(kwargs),
        run_row_pipeline=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("row pipeline unavailable")),
        persist_failure_result=lambda **kwargs: failures.append(kwargs),
    )

    out = adapter.execute(
        context=_context(),
        work=ForgeMatchSessionWorkArtifact(
            session={"id": "sess-1"},
            source_rows=[_source_row()],
            existing_by_source={},
            source_total=1,
        ),
    )

    assert out.status == "completed"
    assert out.failed_count == 1
    assert failures[0]["source_record_id"] == 10
    assert failures[0]["llm_rank"]["reason_codes"] == ["processing_error"]
    assert progress[-1]["source_failed"] == 1


def test_session_execution_adapter_surfaces_unexpected_row_pipeline_failures() -> None:
    failures: list[dict[str, object]] = []

    adapter = ForgeMatchSessionExecutionAdapter(
        is_cancel_requested=lambda **_kwargs: False,
        update_progress=lambda **_kwargs: None,
        run_row_pipeline=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("row pipeline bug")),
        persist_failure_result=lambda **kwargs: failures.append(kwargs),
    )

    with pytest.raises(AssertionError, match="row pipeline bug"):
        adapter.execute(
            context=_context(),
            work=ForgeMatchSessionWorkArtifact(
                session={"id": "sess-1"},
                source_rows=[_source_row()],
                existing_by_source={},
                source_total=1,
            ),
        )

    assert failures == []


def test_session_execution_adapter_handles_domain_errors_as_row_failures() -> None:
    failures: list[dict[str, object]] = []

    adapter = ForgeMatchSessionExecutionAdapter(
        is_cancel_requested=lambda **_kwargs: False,
        update_progress=lambda **_kwargs: None,
        run_row_pipeline=lambda **_kwargs: (_ for _ in ()).throw(ForgeError("candidate lookup failed", status_code=503)),
        persist_failure_result=lambda **kwargs: failures.append(kwargs),
    )

    out = adapter.execute(
        context=_context(),
        work=ForgeMatchSessionWorkArtifact(
            session={"id": "sess-1"},
            source_rows=[_source_row()],
            existing_by_source={},
            source_total=1,
        ),
    )

    assert out.failed_count == 1
    assert "candidate lookup failed" in failures[0]["llm_rank"]["explanation"]


def test_parse_json_dict_returns_none_for_invalid_json() -> None:
    assert _parse_json_dict("{not-json") is None
    assert _parse_json_dict('["not", "dict"]') is None


def test_parse_json_dict_returns_mapping_for_valid_json() -> None:
    assert _parse_json_dict('{"field":"BirthDate"}') == {"field": "BirthDate"}
    assert _parse_json_dict({"field": "BirthDate"}) == {"field": "BirthDate"}
