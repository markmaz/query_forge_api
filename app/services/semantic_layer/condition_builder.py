import logging
from typing import Any, Dict, List

from cohort_ai.adapters.clients import RequestsVectorSearchClient
from cohort_ai.agents.condition import ConditionCodeMappingAgent
from flask import current_app

from app.adapters.databricke_workspace_token_manager import DatabricksWorkspaceTokenManager
from app.config import DATABRICKS_CONDITION_SEARCH_ENDPOINT

logger = logging.getLogger(__name__)

ICD10 = "ICD10CM"


class ConditionBuilder:
    def __init__(self) -> None:
        self.llm = current_app.config.get("COHORT_LLM")

    def build_conditions(self, base_url: str, conditions: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        Build a normalized conditions mapping from a list of condition entities.

        Each item in `conditions` is expected to be a dict like:
        {
            "type": "description" | "code",
            "condition": "<text or code>",
            "negation": bool,
            "logic": "AND" | "OR" | ...
        }
        """
        search_client = RequestsVectorSearchClient(base_url=base_url, auth=DatabricksWorkspaceTokenManager(base_url))
        code_mapping_agent = ConditionCodeMappingAgent(search_client=search_client, search_endpoint=DATABRICKS_CONDITION_SEARCH_ENDPOINT, llm_client=self.llm)

        description_conditions: List[Dict[str, Any]] = []
        code_conditions: List[Dict[str, Any]] = []

        for cond in conditions:
            cond_type = cond.get("type")
            if cond_type == "description":
                description_conditions.append(cond)
            elif cond_type == "code":
                code_conditions.append(cond)
            else:
                logger.debug("Unexpected condition type from NER: %r", cond_type)

        # Build the final condition dictionary
        normalized_conditions: Dict[str, Dict[str, Any]] = {}

        # 1) Conditions that need LLM/code mapping
        self._populate_description_conditions(
            normalized_conditions,
            description_conditions,
            code_mapping_agent,
        )

        # 2) Conditions that are already codes
        self._populate_code_conditions(
            normalized_conditions,
            code_conditions,
        )

        return normalized_conditions

    # ---------- Internals ----------

    def _populate_description_conditions(
        self,
        out: Dict[str, Dict[str, Any]],
        description_conditions: List[Dict[str, Any]],
        code_mapping_agent: ConditionCodeMappingAgent,
    ) -> None:
        """
        Populate `out` with normalized entries for description-based conditions.
        """
        for cond in description_conditions:
            raw_text = cond["condition"]
            base_negation = cond.get("negation")
            base_logic = cond.get("logic")

            condition_search_result = code_mapping_agent.map_condition_code(raw_text, ICD10)
            best_codes_by_term = condition_search_result.get("best_codes") or {}

            # Emit one entry per selected term (first keeps original logic, rest become OR)
            for index, (term, codes_map) in enumerate(best_codes_by_term.items()):
                codes_map = codes_map or {}

                # Normalize codes: remove dots, dedupe, stable order
                codes = ", ".join(
                    sorted({code.replace(".", "") for code in codes_map.keys()})
                )

                # Simple normalization: first letter uppercase, rest lower
                name = term.lower().capitalize()

                logic = base_logic if index == 0 else "OR"

                key = f"{name}-{codes[:100]}" if codes else name

                out[key] = {
                    "name": name,
                    "code": codes,
                    "negation": base_negation,
                    "logic": logic,
                }

    def _populate_code_conditions(
        self,
        out: Dict[str, Dict[str, Any]],
        code_conditions: List[Dict[str, Any]],
    ) -> None:
        """
        Populate `out` with normalized entries for code-based conditions.
        """
        for cond in code_conditions:
            raw_code = cond["condition"]
            code = raw_code.replace(".", "")

            out[code] = {
                "name": code,
                "code": code,
                "negation": cond.get("negation"),
                "logic": cond.get("logic"),
            }
