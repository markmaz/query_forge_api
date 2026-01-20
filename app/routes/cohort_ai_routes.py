import logging

from flask import current_app, jsonify, request
from flask_restx import Namespace, Resource

from app.adapters.databricke_workspace_token_manager import DatabricksWorkspaceTokenManager
from app.adapters.databricks_sql_executor import DatabricksSQLExecutor
from app.config import DEFAULT_COHORT_VECTOR_INDEX_WORKSPACE
from app.decorators.security import token_required
from app.routes._route_utils import get_user_id, get_workspace_id_from_header
from app.services.cohort_builder_vector_sql_json_service import CohortBuilderVectorSqlJsonService
from app.services.domain.domain_table_read_service import DomainTableReadService
from app.services.semantic_layer.semantic_layer_service import SemanticLayer

logging.getLogger(__name__)

cohort_ns = Namespace("cohort_ai", description="Cohort AI namespace")

@cohort_ns.route("/ner")
class CohortNER(Resource):
    @token_required
    def post(self):
        payload = request.get_json(force=True)
        user_text = payload.get("text", "")
        cohort_ner = current_app.config.get("COHORT_NER_AGENT")

        if(cohort_ner):
            result = cohort_ner.extract_medical_entities(user_text)
            return jsonify(result)
        else:
            raise Exception()

@cohort_ns.route("/demographics")
class GetDemographics(Resource):
    @token_required
    def post(self):
        payload = request.get_json(force=True)
        results = SemanticLayer().get_demographics(payload.get("entity", ""))
        return jsonify(results)
        
@cohort_ns.route("/conditions")        
class GetConditions(Resource):
    @token_required
    def post(self):
        payload = request.get_json(force=True)
        results = SemanticLayer().get_conditions(payload.get("entity", ""), DEFAULT_COHORT_VECTOR_INDEX_WORKSPACE)
        return jsonify(results)

@cohort_ns.route("/measurements")
class GetMeasurements(Resource):
    @token_required
    def post(self):
        payload = request.get_json(force=True)
        results = SemanticLayer().get_measurement_codes(payload.get("entity", ""), DEFAULT_COHORT_VECTOR_INDEX_WORKSPACE)
        return jsonify(results)

@cohort_ns.route("/medications")
class GetMedications(Resource):
    @token_required
    def post(self):
        payload = request.get_json(force=True)
        results = SemanticLayer().get_drug_codes(payload.get("entity", ""), payload.get("base_url", ""), payload.get("workspace_id", ""))
        return jsonify(results)

@cohort_ns.route("/procedures")
class GetProcedures(Resource):
    @token_required
    def post(self):
        payload = request.get_json(force=True)
        results = SemanticLayer().get_procedure_codes(payload.get("entity", ""), DEFAULT_COHORT_VECTOR_INDEX_WORKSPACE)
        return jsonify(results)
    
@cohort_ns.route("/sql")
class GetSQL(Resource):
    @token_required
    def post(self):
        payload = request.get_json(force=True)
        sql = payload.get("sql", "")
        host = payload.get("host", "")
        warehouse = payload.get("warehouse_id")
        base_url = host
        token_manager = DatabricksWorkspaceTokenManager(base_url)
        sql_exe = DatabricksSQLExecutor(base_url=base_url, token_provider=token_manager, default_warehouse_id=warehouse)
        results = sql_exe.submit_statement(sql, result_format="ARROW_STREAM")
        table = results["table"]              # pyarrow.Table
        rows = table.to_pylist()              # list[dict], JSON-serializable
        return jsonify(rows)
        # return jsonify(results)


@cohort_ns.route("/domain")
class GetDomain(Resource):
    @token_required
    def get(self):
        workspace_id = get_workspace_id_from_header()
        domain_name = "Cohort Builder"
        result = DomainTableReadService().get_domain(workspace_id=workspace_id, domain_name=domain_name)
        return jsonify(result)


@cohort_ns.route("/vector-sqljson")
class CohortVectorSqlJson(Resource):
    @token_required
    def post(self):
        payload = request.get_json(force=True) or {}
        workspace_id = get_workspace_id_from_header()
        user_id = get_user_id()

        demographics = payload.get("demographics") or {}
        conditions = payload.get("conditions") or {}
        procedures = payload.get("procedures") or {}
        drugs = payload.get("drugs") or {}

        sql_json = CohortBuilderVectorSqlJsonService().build(
            workspace_id=workspace_id,
            user_id=user_id,
            demographics=demographics,
            conditions=conditions,
            procedures=procedures,
            drugs=drugs,
        )
        return jsonify(sql_json)
