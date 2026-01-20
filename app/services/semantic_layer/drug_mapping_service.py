from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import pyarrow as pa
import requests
from cohort_ai.agents.drug import DrugCodeMappingAgent  # or wherever it lives
from flask import current_app

from app.adapters.databricke_workspace_token_manager import DatabricksWorkspaceTokenManager
from app.adapters.databricks_sql_executor import DatabricksSQLExecutor
from app.config import DATABRICKS_DRUG_REFERENCE_TABLE, DEFAULT_SQL_WAREHOUSE
from app.services.warehouse_service import WarehouseService

logger = logging.getLogger(__name__)


class UmlsClient:
    """
    Minimal interface for UMLS / RxNav calls.
    Implement this around your existing HTTP client.

    get_approximate_match should return something like:
    {
      "approximateGroup": {
        "candidate": [
          {"rxcui": "1234", "rank": "1", ...},
          ...
        ]
      }
    }
    """

    def get_approximate_match(
        self,
        term: str,
        max_entries: int,
        option: int = 1,
    ) -> Dict[str, Any]:
        base_url = "https://rxnav.nlm.nih.gov/REST/approximateTerm.json"
        params = {"term": term, "maxEntries": max_entries, "option": option}

        response = requests.get(base_url, params=params)

        if not response:
            return {}

        return response.json()


class DrugMappingService:
    """
    Orchestrates:
      - UMLS (RXCUI lookup)
      - Databricks SQL (drug_reference table)
      - DrugCodeMappingAgent (LLM ranking)

    Exposes map_drug_code() with the same contract your builder expects.
    """

    def __init__(
        self,
        base_url: str,
        workspace_id: str
    ) -> None:
        warehouse_id = WarehouseService().get_warehouse_by_name(workspace_id=workspace_id, warehouse_name=DEFAULT_SQL_WAREHOUSE).get("warehouse_id")
        self.sql_exe = DatabricksSQLExecutor(default_warehouse_id=warehouse_id, base_url=base_url, token_provider=DatabricksWorkspaceTokenManager(base_url))
        self.umls_client = UmlsClient()
        self.ai_agent = DrugCodeMappingAgent(llm_client=current_app.config.get("COHORT_LLM"))
        self.drug_table = DATABRICKS_DRUG_REFERENCE_TABLE

    # ---------- Public API ----------

    def map_drug_code(self, medication: str) -> Dict[str, Any]:
        """
        Full pipeline: UMLS -> Databricks -> LLM.

        Returns:
            {
              "best_codes": { term: [ndc1, ndc2, ...], ... },
              "confidence": int | None,
              "candidates": { term: [ndc1, ndc2, ...], ... },
            }
        """
        # 1) UMLS → list of (rxcui, rank)
        rxcui_rows = self._get_rxcui_candidates(medication)
        if not rxcui_rows:
            return {"best_codes": {}, "confidence": None, "candidates": {}}

        # 2) Databricks → {display_term: [ndc_codes]}
        candidates_data = self._get_drug_candidates_from_databricks(rxcui_rows)
        candidate_terms = list(candidates_data.keys())

        if not candidate_terms:
            return {"best_codes": {}, "confidence": None, "candidates": candidates_data}

        # 3) AI agent → which terms are best?
        selected_terms, confidence = self.ai_agent.rank_candidates(
            medication,
            candidate_terms,
            few_shots_override=None,  # few-shots live in YAML
        )

        # 4) Build best_codes: term → list of NDCs
        best_codes: Dict[str, List[str]] = {}
        for t in selected_terms:
            if t in candidates_data:
                best_codes[t] = candidates_data[t]

        # Fallback: if nothing selected, default to top-1 candidate
        if not best_codes and candidate_terms:
            top_term = candidate_terms[0]
            best_codes = {top_term: candidates_data[top_term]}

        return {
            "best_codes": best_codes,
            "confidence": confidence,
            "candidates": candidates_data,
        }

    # ---------- Internals ----------

    def _get_rxcui_candidates(
        self,
        medication: str,
        max_results: Optional[int] = 50,
    ) -> List[Tuple[int, int]]:
        """
        Call UMLS / RxNav approxTerm to get (rxcui, rank) pairs.
        """
        resp = self.umls_client.get_approximate_match(
            term=medication,
            max_entries=max_results,
            option=1,
        )
        approx_group = (resp or {}).get("approximateGroup") or {}
        candidate = approx_group.get("candidate") or []

        rows: List[Tuple[int, int]] = []
        for row in candidate:
            try:
                rxcui = int(row.get("rxcui"))
                rank = int(row.get("rank", 0))
            except (TypeError, ValueError):
                continue
            rows.append((rxcui, rank))

        return rows

    def _get_drug_candidates_from_databricks(
        self,
        rxcui_rows: List[Tuple[int, int]],
    ) -> Dict[str, List[str]]:
        """
        Given RXCUIs, query the drug reference table in Databricks to get
        product_name, drug_names, and ndc_codes.

        Returns:
            { "Product Name (drug1, drug2)": ["ndc1", "ndc2", ...], ... }
        """
        if not rxcui_rows:
            return {}

        # Build VALUES clause: (CAST(rxcui AS BIGINT), rank)
        values_sql = ",\n    ".join(
            f"(CAST({rxcui} AS BIGINT), {rank})"
            for rxcui, rank in rxcui_rows
        )

        sql = f"""
        WITH rxcui_matches AS (
          SELECT * FROM VALUES
            {values_sql}
          AS t(rxcui, rank)
        )
        SELECT
          r.product_name,
          collect_set(r.drug_name) AS drug_names,
          collect_set(r.ndc_code) AS ndc_codes
        FROM {self.drug_table} r
        JOIN rxcui_matches m
          ON r.rxcui = m.rxcui
        WHERE r.product_name IS NOT NULL
          AND r.drug_name IS NOT NULL
          AND r.ndc_code IS NOT NULL
        GROUP BY r.product_name
        """

        res = self.sql_exe.submit_statement(sql, result_format="ARROW_STREAM")
        table: pa.Table = res["table"]

        # Arrow schema assumed:
        #   product_name: string
        #   drug_names:   list<string>
        #   ndc_codes:    list<string>
        out: Dict[str, List[str]] = {}

        for row in table.to_pylist():
            product = row["product_name"]
            drug_names = row.get("drug_names") or []
            ndcs = [str(n) for n in (row.get("ndc_codes") or [])]

            # "Product (name1, name2)"
            drug_names_str = ", ".join(drug_names)
            label = f"{product} ({drug_names_str})" if drug_names_str else product

            out[label] = ndcs

        return out
