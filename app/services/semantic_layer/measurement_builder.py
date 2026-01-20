import logging
from typing import Any, Dict, List

from cohort_ai.adapters.clients import RequestsVectorSearchClient
from cohort_ai.agents.measurement_code import MeasurementCodeMappingAgent
from cohort_ai.agents.measurement_unit_code import MeasurementUnitCodeMappingAgent
from flask import current_app

from app.adapters.databricke_workspace_token_manager import DatabricksWorkspaceTokenManager
from app.config import (
    DATABRICKS_MEASUREMENT_SEARCH_ENDPOINT,
    DATABRICKS_MEASUREMENT_UNIT_SEARCH_ENDPOINT,
)

logger = logging.getLogger(__name__)


class MeasurementBuilder:
    def __init__(self) -> None:
        self.llm = current_app.config.get("COHORT_LLM")

    def build_measurements(
        self,
        measurements: List[Dict[str, Any]],
        base_url: str,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Build a normalized measurements mapping from a list of measurement entities.

        Each item in `measurements` is expected to be a dict like:
        {
            "type": "description" | "code",
            "measurement_name": str,
            "measurement_unit": str | None,
            "measurement_value": Any,
            "logic": str,
        }
        """
        vector_search = RequestsVectorSearchClient(
            base_url=base_url,
            auth=DatabricksWorkspaceTokenManager(base_url),
        )

        meas_code_agent = MeasurementCodeMappingAgent(
            llm_client=self.llm,
            measurement_search_endpoint=DATABRICKS_MEASUREMENT_SEARCH_ENDPOINT,
            search_client=vector_search,
        )

        unit_code_agent = MeasurementUnitCodeMappingAgent(
            llm_client=self.llm,
            measurement_unit_search_endpoint=DATABRICKS_MEASUREMENT_UNIT_SEARCH_ENDPOINT,
            search_client=vector_search,
        )

        description_measurements: List[Dict[str, Any]] = []
        code_measurements: List[Dict[str, Any]] = []

        # Split into description-based vs code-based measurements
        for m in measurements:
            m_type = m.get("type")
            if m_type == "description":
                description_measurements.append(m)
            elif m_type == "code":
                code_measurements.append(m)
            else:
                logger.debug("Unexpected measurement type from NER: %r", m_type)

        result: Dict[str, Dict[str, Any]] = {}

        self._populate_description_measurements(
            out=result,
            description_measurements=description_measurements,
            meas_code_agent=meas_code_agent,
            unit_code_agent=unit_code_agent,
        )

        self._populate_code_measurements(
            out=result,
            code_measurements=code_measurements,
            unit_code_agent=unit_code_agent,
        )

        return result

    # ---------- Internals ----------

    def _populate_description_measurements(
        self,
        out: Dict[str, Dict[str, Any]],
        description_measurements: List[Dict[str, Any]],
        meas_code_agent: MeasurementCodeMappingAgent,
        unit_code_agent: MeasurementUnitCodeMappingAgent,
    ) -> None:
        """
        Handle measurements where we start from a natural-language description.
        """
        for entity in description_measurements:
            name_raw = entity["measurement_name"]
            unit_raw = entity.get("measurement_unit") or ""
            value = entity.get("measurement_value")
            base_logic = entity.get("logic")

            # Map measurement description to codes
            meas_search_result = meas_code_agent.map_measurement_code(
                name_raw,
                unit_raw,
                None,  # third arg is kept as in original
            )
            best_measurement_dict = meas_search_result.get("best_codes") or {}

            # Map measurement unit to a standard unit code (optional)
            if unit_raw:
                unit_search_result = unit_code_agent.map_unit_code(unit_raw, name_raw)
                best_unit_dict = unit_search_result.get("best_codes") or {}
            else:
                best_unit_dict = {}

            # Emit one entry per selected measurement (first preserves original logic, rest become OR)
            for index, (best_name, code_str) in enumerate(best_measurement_dict.items()):
                # best_name is a description from the mapping;
                # code_str is the code returned by the agent
                mapped_name = best_name.capitalize()
                logic = base_logic if index == 0 else "OR"

                key = f"{mapped_name}-{code_str}"

                out[key] = {
                    "name": mapped_name,
                    "code": int(code_str),
                    "unit": best_unit_dict,
                    "value": value,
                    "logic": logic,
                }

    def _populate_code_measurements(
        self,
        out: Dict[str, Dict[str, Any]],
        code_measurements: List[Dict[str, Any]],
        unit_code_agent: MeasurementUnitCodeMappingAgent,
    ) -> None:
        """
        Handle measurements where the measurement itself is already a code.
        """
        for entity in code_measurements:
            code_str = entity["measurement_name"]
            unit_raw = entity.get("measurement_unit") or ""
            value = entity.get("measurement_value")
            logic = entity.get("logic")

            # Map unit if we have one
            if unit_raw:
                unit_search_result = unit_code_agent.map_unit_code(unit_raw, "")
                best_unit_dict = unit_search_result.get("best_codes") or {}
            else:
                best_unit_dict = {}

            out[code_str] = {
                "name": int(code_str),
                "code": int(code_str),
                "unit": best_unit_dict,
                "value": value,
                "logic": logic,
            }