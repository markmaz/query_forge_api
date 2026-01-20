import logging
from typing import Dict

from flask import current_app

from app.exceptions.service_error import ServiceError
from app.services.semantic_layer.condition_builder import ConditionBuilder
from app.services.semantic_layer.demographics_builder import DemographicsBuilder
from app.services.semantic_layer.drug_builder import DrugBuilder
from app.services.semantic_layer.drug_mapping_service import DrugMappingService
from app.services.semantic_layer.measurement_builder import MeasurementBuilder
from app.services.semantic_layer.procedure_builder import ProcedureBuilder

logger = logging.getLogger(__name__)

class SemanticLayer():
    def __init__(self):
        self.llm = current_app.config.get("COHORT_LLM")

    def get_conditions(self, entity_response: Dict, base_url: str) -> Dict:
        conditions = entity_response.get("medical_condition")

        if conditions:
            condition_builder = ConditionBuilder()
            return condition_builder.build_conditions(base_url=base_url, conditions=conditions)
        else:
            raise ServiceError(message="No medical conditions found", status_code=404)

    def get_drug_codes(self, entity_response: Dict, base_url: str, workspace_id: str) -> Dict:
        medications = entity_response.get("medication")

        if medications:
            drug_mapping_service = DrugMappingService(base_url=base_url, workspace_id=workspace_id)
            builder = DrugBuilder(drug_code_mapping_agent=drug_mapping_service)
            return builder.build_drugs(medications)
        else:
            raise ServiceError(message="Medication not found", status_code=404)


    def get_procedure_codes(self, entity_response: Dict, base_url: str) -> Dict:
        procedures = entity_response.get("medical_procedure")

        if procedures:
            return ProcedureBuilder().build_procedures(procedures=procedures, base_url=base_url)
        else:
            raise ServiceError(message="Procedures not found", status_code=404)

    def get_measurement_codes(self, entity_response: Dict, base_url: str) -> Dict:
        measurements = entity_response.get("lab_vital_measurement")

        if measurements:
            return MeasurementBuilder().build_measurements(measurements=measurements, base_url=base_url)
        else:
            raise ServiceError(message="No measurements found", status_code=404)

    def get_demographics(self, entity_response: Dict) -> Dict:
        return DemographicsBuilder().build_demographics(entity=entity_response)
        

