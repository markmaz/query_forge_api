from __future__ import annotations

import pyarrow as pa

from app.services.semantic_layer.drug_mapping_service import DrugMappingService
from tests._support.fakes import FakeDatabricksSQLExecutor


class _DummyUmls:
    def __init__(self, payload) -> None:
        self.payload = payload

    def get_approximate_match(self, term: str, max_entries: int, option: int = 1):
        return self.payload


class _DummyAgent:
    def rank_candidates(self, *_args, **_kwargs):
        return ["BestTerm"], 0.9


def test_get_rxcui_candidates_filters_invalid() -> None:
    svc = object.__new__(DrugMappingService)
    svc.umls_client = _DummyUmls(
        {
            "approximateGroup": {
                "candidate": [
                    {"rxcui": "123", "rank": "1"},
                    {"rxcui": "bad", "rank": "x"},
                ]
            }
        }
    )
    rows = DrugMappingService._get_rxcui_candidates(svc, "drug")
    assert rows == [(123, 1)]


def test_get_drug_candidates_from_databricks() -> None:
    svc = object.__new__(DrugMappingService)
    sql = FakeDatabricksSQLExecutor()
    sql.submit_responses.append(
        {
            "table": pa.Table.from_pylist(
                [
                    {
                        "product_name": "Ozempic",
                        "drug_names": ["semaglutide"],
                        "ndc_codes": ["001", "002"],
                    }
                ]
            )
        }
    )
    svc.sql_exe = sql
    svc.drug_table = "main.drug_table"

    out = DrugMappingService._get_drug_candidates_from_databricks(svc, [(123, 1)])
    assert "Ozempic (semaglutide)" in out
    assert out["Ozempic (semaglutide)"] == ["001", "002"]


def test_map_drug_code_end_to_end() -> None:
    svc = object.__new__(DrugMappingService)
    svc._get_rxcui_candidates = lambda _med: [(1, 1)]
    svc._get_drug_candidates_from_databricks = lambda _rows: {"BestTerm": ["001"]}
    svc.ai_agent = _DummyAgent()

    result = DrugMappingService.map_drug_code(svc, "drug")
    assert result["best_codes"] == {"BestTerm": ["001"]}


def test_map_drug_code_no_candidates() -> None:
    svc = object.__new__(DrugMappingService)
    svc._get_rxcui_candidates = lambda _med: []
    result = DrugMappingService.map_drug_code(svc, "drug")
    assert result["best_codes"] == {}


def test_map_drug_code_fallback_to_top_candidate() -> None:
    svc = object.__new__(DrugMappingService)
    svc._get_rxcui_candidates = lambda _med: [(1, 1)]
    svc._get_drug_candidates_from_databricks = lambda _rows: {"TopTerm": ["001"]}

    class _NoPickAgent:
        def rank_candidates(self, *_args, **_kwargs):
            return [], None

    svc.ai_agent = _NoPickAgent()
    result = DrugMappingService.map_drug_code(svc, "drug")
    assert result["best_codes"] == {"TopTerm": ["001"]}
