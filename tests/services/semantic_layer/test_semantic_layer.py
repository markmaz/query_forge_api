from __future__ import annotations

import pytest

from app.exceptions.service_error import ServiceError
from app.services.semantic_layer.condition_builder import ConditionBuilder
from app.services.semantic_layer.demographics_builder import DemographicsBuilder
from app.services.semantic_layer.drug_builder import DrugBuilder
from app.services.semantic_layer.measurement_builder import MeasurementBuilder
from app.services.semantic_layer.procedure_builder import ProcedureBuilder
from app.services.semantic_layer.semantic_layer_service import SemanticLayer


def test_condition_builder_builds(app, monkeypatch) -> None:
    class DummySearchClient:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class DummyAgent:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        def map_condition_code(self, text: str, code_set: str) -> dict:
            return {"best_codes": {"Diabetes": {"E11": 1}}}

    monkeypatch.setattr(
        "app.services.semantic_layer.condition_builder.RequestsVectorSearchClient",
        DummySearchClient,
    )
    monkeypatch.setattr(
        "app.services.semantic_layer.condition_builder.DatabricksWorkspaceTokenManager",
        lambda *_args, **_kwargs: "token",
    )
    monkeypatch.setattr(
        "app.services.semantic_layer.condition_builder.ConditionCodeMappingAgent",
        DummyAgent,
    )

    with app.app_context():
        builder = ConditionBuilder()
        out = builder.build_conditions(
            base_url="https://dbx",
            conditions=[
                {"type": "description", "condition": "diabetes", "negation": False, "logic": "AND"},
                {"type": "code", "condition": "E11", "negation": True, "logic": "OR"},
            ],
        )

    assert any(v["code"] == "E11" for v in out.values())


def test_procedure_builder_builds(app, monkeypatch) -> None:
    class DummyAgent:
        def map_procedure_code(self, raw: str, code_set: str) -> dict:
            if code_set == "CPT4":
                return {"best_codes": {"Bypass": "43846"}}
            return {"best_codes": {"Sleeve": "43775"}}

    monkeypatch.setattr(ProcedureBuilder, "_make_agent", lambda *_args, **_kwargs: DummyAgent())

    with app.app_context():
        out = ProcedureBuilder().build_procedures(
            procedures=[
                {"type": "description", "procedure": "bypass", "logic": "AND"},
                {"type": "code", "procedure": "C9784", "logic": "OR"},
            ],
            base_url="https://dbx",
        )

    assert "Bypass-43846" in out
    assert out["C9784"]["code"] == "C9784"


def test_measurement_builder_builds(app, monkeypatch) -> None:
    class DummySearchClient:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    class DummyMeasAgent:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        def map_measurement_code(self, *_args, **_kwargs) -> dict:
            return {"best_codes": {"Glucose": "123"}}

    class DummyUnitAgent:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        def map_unit_code(self, *_args, **_kwargs) -> dict:
            return {"best_codes": {"mg/dL": "mg/dL"}}

    monkeypatch.setattr(
        "app.services.semantic_layer.measurement_builder.RequestsVectorSearchClient",
        DummySearchClient,
    )
    monkeypatch.setattr(
        "app.services.semantic_layer.measurement_builder.DatabricksWorkspaceTokenManager",
        lambda *_args, **_kwargs: "token",
    )
    monkeypatch.setattr(
        "app.services.semantic_layer.measurement_builder.MeasurementCodeMappingAgent",
        DummyMeasAgent,
    )
    monkeypatch.setattr(
        "app.services.semantic_layer.measurement_builder.MeasurementUnitCodeMappingAgent",
        DummyUnitAgent,
    )

    with app.app_context():
        out = MeasurementBuilder().build_measurements(
            measurements=[
                {
                    "type": "description",
                    "measurement_name": "glucose",
                    "measurement_unit": "mg/dL",
                    "measurement_value": 126,
                    "logic": "AND",
                },
                {
                    "type": "code",
                    "measurement_name": "456",
                    "measurement_unit": None,
                    "measurement_value": 7.1,
                    "logic": "OR",
                },
            ],
            base_url="https://dbx",
        )

    assert any(v["code"] == 123 for v in out.values())
    assert "456" in out


def test_drug_builder_builds() -> None:
    class DummyDrugAgent:
        def map_drug_code(self, drug: str) -> dict:
            return {"best_codes": {"Ozempic": ["001", "002"]}}

    builder = DrugBuilder(DummyDrugAgent())
    out = builder.build_drugs(
        medications=[
            {"type": "description", "drug": "Ozempic", "logic": "AND"},
            {"type": "code", "drug": "1234-567-89", "logic": "OR"},
        ]
    )

    assert any(v["code"].startswith("001") for v in out.values())
    assert "123456789" in out


def test_drug_builder_code_paths() -> None:
    class DummyDrugAgent:
        def map_drug_code(self, drug: str) -> dict:
            return {"best_codes": {}}

    builder = DrugBuilder(DummyDrugAgent())
    out = builder.build_drugs(
        medications=[
            {"type": "code", "drug": "12345-678-90", "logic": "AND"},
            {"type": "code", "drug": "bad-code", "logic": "OR"},
            {"type": "unknown", "drug": "ignored", "logic": "OR"},
        ]
    )

    assert "1234567890" in out
    assert "bad-code" in out


def test_drug_builder_ndc_to_11_invalid() -> None:
    builder = DrugBuilder(None)
    with pytest.raises(ValueError):
        builder.ndc_to_11("1-2")


def test_demographics_builder() -> None:
    builder = DemographicsBuilder()
    out = builder.build_demographics({"age": {"lower_bound": 30, "upper_bound": 40}, "gender": ["F"]})
    assert out["age"]["lower_bound"] == 30


def test_semantic_layer_service(app, monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.semantic_layer.semantic_layer_service.ConditionBuilder.build_conditions",
        lambda *_args, **_kwargs: {"ok": True},
    )
    monkeypatch.setattr(
        "app.services.semantic_layer.semantic_layer_service.DrugMappingService",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        "app.services.semantic_layer.semantic_layer_service.DrugBuilder.build_drugs",
        lambda *_args, **_kwargs: {"drug": True},
    )
    monkeypatch.setattr(
        "app.services.semantic_layer.semantic_layer_service.ProcedureBuilder.build_procedures",
        lambda *_args, **_kwargs: {"proc": True},
    )
    monkeypatch.setattr(
        "app.services.semantic_layer.semantic_layer_service.MeasurementBuilder.build_measurements",
        lambda *_args, **_kwargs: {"meas": True},
    )

    with app.app_context():
        service = SemanticLayer()
        assert service.get_conditions({"medical_condition": [{"type": "code", "condition": "E11"}]}, "u") == {
            "ok": True
        }
        assert service.get_drug_codes({"medication": [{"type": "code", "drug": "123"}]}, "u", "ws") == {
            "drug": True
        }
        assert service.get_procedure_codes({"medical_procedure": [{"type": "code", "procedure": "123"}]}, "u") == {
            "proc": True
        }
        assert service.get_measurement_codes({"lab_vital_measurement": [{"type": "code", "measurement_name": "1"}]}, "u") == {
            "meas": True
        }
        assert service.get_demographics({"age": {"lower_bound": 1, "upper_bound": 2}})["age"]["upper_bound"] == 2

    with pytest.raises(ServiceError):
        service.get_conditions({}, "u")
    with pytest.raises(ServiceError):
        service.get_drug_codes({}, "u", "ws")
    with pytest.raises(ServiceError):
        service.get_procedure_codes({}, "u")
    with pytest.raises(ServiceError):
        service.get_measurement_codes({}, "u")
