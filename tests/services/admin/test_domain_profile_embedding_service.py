from __future__ import annotations

import json

from app.exceptions.forge_error import ForgeError
from app.models.domain.domain_profile import compute_content_hash
from app.services.admin.domain_profile_embedding_service import (
    DomainProfileEmbeddingService,
    _build_user_prompt,
)


class _FakeSQL:
    def __init__(self, *, existing_row=None, domain_ids=None) -> None:
        self.existing_row = existing_row
        self.domain_ids = list(domain_ids or [15])
        self.writes = []

    def execute_query_mappings(self, query: str, params=None):
        if "FROM domain_profile" in query and "LIMIT 1" in query:
            return [self.existing_row] if self.existing_row else []
        if "FROM domain" in query and "ORDER BY id ASC" in query:
            return [{"id": did} for did in self.domain_ids]
        return []

    def execute_write(self, query: str, params=None):
        self.writes.append({"query": query, "params": dict(params or {})})
        return 1


class _FakeBuilder:
    def build_domain_context(self, *, workspace_id: str, domain_id: int):
        if int(domain_id) == 99:
            raise ForgeError("Domain not found", status_code=404)
        return {
            "workspace_id": workspace_id,
            "domain": {
                "domain_id": int(domain_id),
                "name": "ADM",
                "description": "Average Daily Membership",
            },
            "tables": [
                {
                    "workspace_table_id": 34,
                    "table_name": "fct_student_base_adm",
                    "columns": [
                        {
                            "column_name": "normalized_adm",
                            "data_type": "double",
                            "description": "Normalized ADM",
                        }
                    ],
                }
            ],
            "joins": [],
            "relationship_lines": [],
            "stats": {"table_count": 1, "column_count": 1, "join_count": 0},
        }


class _FakeEmbeddingModel:
    def __init__(self) -> None:
        self.calls = 0

    def encode(self, texts, *, normalize=True, batch_size=1):
        del normalize, batch_size
        self.calls += 1
        return [[0.1] * 384 for _ in list(texts)]


class _FakeLLM:
    def __init__(self, traces) -> None:
        self.traces = list(traces)
        self.calls = 0

    def chat_json_with_trace(self, **kwargs):
        del kwargs
        idx = self.calls if self.calls < len(self.traces) else len(self.traces) - 1
        self.calls += 1
        return dict(self.traces[idx])


def _payload(embedding_text: str = "ADM domain semantic text"):
    return {
        "summary": "ADM profile",
        "keywords": ["adm", "attendance"],
        "entities": ["student", "school"],
        "metrics": ["total_adm"],
        "synonyms": [{"term": "ADM", "means": ["Average Daily Membership"]}],
        "acronyms": [{"abbr": "ADM", "expansion": "Average Daily Membership"}],
        "notes": "Used for state reporting",
        "attributes": ["school_year", "report_period"],
        "embedding_text": embedding_text,
    }


def test_generate_one_hash_changed_generates_embedding_and_upserts():
    payload = _payload("fresh embedding text")
    llm = _FakeLLM(
        [
            {
                "parsed": payload,
                "content": json.dumps(payload),
                "raw_text": json.dumps({"model": "qwen3.5", "usage": {"prompt_tokens": 100}}),
            }
        ]
    )
    emb = _FakeEmbeddingModel()
    sql = _FakeSQL(existing_row=None)

    svc = DomainProfileEmbeddingService(
        sql=sql,
        builder=_FakeBuilder(),
        llm_client=llm,
        embedding_model=emb,
    )

    out = svc.generate_one(workspace_id="ws-1", domain_id=15)

    assert out["status"] == "generated"
    assert out["hash_changed"] is True
    assert out["embedding_generated"] is True
    assert emb.calls == 1
    assert sql.writes
    assert sql.writes[-1]["params"]["content_hash"] == compute_content_hash("fresh embedding text")


def test_generate_one_skips_embedding_when_hash_unchanged():
    same_text = "same embedding text"
    payload = _payload(same_text)
    llm = _FakeLLM([{"parsed": payload, "content": json.dumps(payload), "raw_text": json.dumps(payload)}])
    existing = {
        "id": 10,
        "content_hash": compute_content_hash(same_text),
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "embedded_at": "2026-03-01 00:00:00",
    }
    emb = _FakeEmbeddingModel()
    sql = _FakeSQL(existing_row=existing)

    svc = DomainProfileEmbeddingService(
        sql=sql,
        builder=_FakeBuilder(),
        llm_client=llm,
        embedding_model=emb,
    )

    out = svc.generate_one(workspace_id="ws-1", domain_id=15)

    assert out["status"] == "unchanged"
    assert out["hash_changed"] is False
    assert out["embedding_generated"] is False
    assert emb.calls == 0


def test_generate_one_extracts_json_wrapped_in_text():
    payload = _payload("wrapped text")
    wrapped = f"here\n{json.dumps(payload)}\nthanks"
    llm = _FakeLLM([{"parsed": None, "content": wrapped, "raw_text": wrapped}])
    sql = _FakeSQL(existing_row=None)

    svc = DomainProfileEmbeddingService(
        sql=sql,
        builder=_FakeBuilder(),
        llm_client=llm,
        embedding_model=_FakeEmbeddingModel(),
    )

    out = svc.generate_one(workspace_id="ws-1", domain_id=15)
    assert out["status"] == "generated"


def test_generate_one_retries_after_invalid_json_then_succeeds():
    payload = _payload("retry text")
    llm = _FakeLLM(
        [
            {"parsed": None, "content": "not-json", "raw_text": "not-json"},
            {"parsed": payload, "content": json.dumps(payload), "raw_text": json.dumps(payload)},
        ]
    )
    sql = _FakeSQL(existing_row=None)

    svc = DomainProfileEmbeddingService(
        sql=sql,
        builder=_FakeBuilder(),
        llm_client=llm,
        embedding_model=_FakeEmbeddingModel(),
    )

    out = svc.generate_one(workspace_id="ws-1", domain_id=15)
    assert out["status"] == "generated"
    assert llm.calls == 2


def test_generate_many_continues_when_one_domain_fails():
    payload = _payload("batch text")
    llm = _FakeLLM([{"parsed": payload, "content": json.dumps(payload), "raw_text": json.dumps(payload)}])
    sql = _FakeSQL(existing_row=None)

    svc = DomainProfileEmbeddingService(
        sql=sql,
        builder=_FakeBuilder(),
        llm_client=llm,
        embedding_model=_FakeEmbeddingModel(),
    )

    out = svc.generate_many(workspace_id="ws-1", domain_ids=[15, 99])

    assert out["total"] == 2
    assert out["generated"] == 1
    assert out["failed"] == 1
    failed_rows = [row for row in out["results"] if row.get("status") == "failed"]
    assert failed_rows


def test_generate_all_loads_domain_ids_and_processes_batch():
    payload = _payload("all text")
    llm = _FakeLLM([{"parsed": payload, "content": json.dumps(payload), "raw_text": json.dumps(payload)}])
    sql = _FakeSQL(existing_row=None, domain_ids=[15, 16])

    svc = DomainProfileEmbeddingService(
        sql=sql,
        builder=_FakeBuilder(),
        llm_client=llm,
        embedding_model=_FakeEmbeddingModel(),
    )

    out = svc.generate_all(workspace_id="ws-1")

    assert out["total"] == 2


def test_build_user_prompt_compacts_large_domain_context():
    context = {
        "workspace_id": "ws-1",
        "domain": {
            "domain_id": 12,
            "name": "Large Domain",
            "description": "A" * 500,
        },
        "tables": [
            {
                "workspace_table_id": table_index,
                "table_name": f"table_{table_index}",
                "description": "B" * 300,
                "columns": [
                    {
                        "column_name": f"column_{column_index}",
                        "data_type": "string",
                        "description": "C" * 200,
                    }
                    for column_index in range(20)
                ],
            }
            for table_index in range(20)
        ],
        "joins": [{"from_table_name": "a", "to_table_name": "b", "join_type": "LEFT", "join_spec": {}}] * 20,
        "relationship_lines": [f"line {i}" for i in range(20)],
        "stats": {"table_count": 20, "column_count": 400, "join_count": 20},
    }

    prompt = _build_user_prompt(context=context)

    assert "\"tables_included_in_prompt\": 12" in prompt
    assert "\"tables_omitted_from_prompt\": 8" in prompt
    assert "\"columns_omitted_from_prompt\"" in prompt
    assert "A" * 300 not in prompt
