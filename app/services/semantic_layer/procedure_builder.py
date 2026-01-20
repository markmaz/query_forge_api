import logging
from typing import Any, Dict, List

from cohort_ai.adapters.clients import RequestsVectorSearchClient
from cohort_ai.agents.procedure import ProcedureCodeMappingAgent
from flask import current_app

from app.adapters.databricke_workspace_token_manager import DatabricksWorkspaceTokenManager
from app.config import DATABRICKS_PROCEDURE_SEARCH_ENDPOINT

logger = logging.getLogger(__name__)


class ProcedureBuilder:
    def __init__(self) -> None:
        """
        Uses COHORT_LLM from the current Flask app config.
        """
        self.llm = current_app.config.get("COHORT_LLM")

    def _make_agent(self, base_url: str) -> ProcedureCodeMappingAgent:
        """
        Construct a ProcedureCodeMappingAgent wired to Databricks vector search.
        """
        vector_search = RequestsVectorSearchClient(
            base_url=base_url,
            auth=DatabricksWorkspaceTokenManager(base_url),
        )
        return ProcedureCodeMappingAgent(
            llm_client=self.llm,
            search_client=vector_search,
            procedure_search_endpoint=DATABRICKS_PROCEDURE_SEARCH_ENDPOINT,
        )

    def build_procedures(
        self,
        procedures: List[Dict[str, Any]],
        base_url: str,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Convert NER procedure entities into a normalized procedure mapping dict.

        `procedures` items look like:
        {
          "type": "description" | "code",
          "procedure": "<string>",
          "negation": bool,
          "logic": "AND" | "OR" | ...
        }

        Returns:
            {
              "<display_key>": {
                 "name": <display_name>,
                 "code": <code_string>,
                 "negation": bool,
                 "logic": "AND"/"OR",
              },
              ...
            }
        """
        agent = self._make_agent(base_url)

        description_entities: List[Dict[str, Any]] = []
        code_entities: List[Dict[str, Any]] = []

        for ent in procedures:
            t = ent.get("type")
            if t == "description":
                description_entities.append(ent)
            elif t == "code":
                code_entities.append(ent)
            else:
                logger.debug("Unexpected procedure type from NER: %r", t)

        dict_procedure: Dict[str, Dict[str, Any]] = {}

        for ent in description_entities:
            raw_proc = ent["procedure"]
            negation = ent.get("negation")
            base_logic = ent.get("logic")

            first_for_proc = True

            for code_set in ["CPT4", "HCPCS"]:
                mapping = agent.map_procedure_code(raw_proc, code_set)
                best_codes_map = mapping.get("best_codes") or {}

                for proc_name, code in best_codes_map.items():
                    if code in dict_procedure:
                        continue

                    name = proc_name.capitalize()
                    logic = base_logic if first_for_proc else "OR"
                    first_for_proc = False

                    key = f"{name}-{code}"

                    dict_procedure[key] = {
                        "name": name,
                        "code": code,
                        "negation": negation,
                        "logic": logic,
                    }

        for ent in code_entities:
            raw_code = ent["procedure"]
            negation = ent.get("negation")
            logic = ent.get("logic")

            code = raw_code.replace(" ", "") if raw_code else raw_code

            dict_procedure[code] = {
                "name": code,
                "code": code,
                "negation": negation,
                "logic": logic,
            }

        return dict_procedure
