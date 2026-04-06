from __future__ import annotations

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.domain.domain_recommendation_service import DomainRecommendationService


class _FakeSql:
    def __init__(self, rows):
        self.rows = rows

    def execute_query_mappings(self, query, params=None):
        if "FROM workspace_column" in query:
            ids = set((params or {}).values())
            out = []
            for row in self.rows:
                if row.get("workspace_table_id") in ids:
                    out.append(dict(row))
            return out
        del query, params
        return list(self.rows)


class _FakeLlm:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def chat_json(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.payload)


class _FakeDomainAdminWriteService:
    def __init__(self):
        self.calls = []
        self.next_id = 100

    def create_domain(self, **kwargs):
        self.calls.append(kwargs)
        self.next_id += 1
        return {"id": self.next_id, "name": kwargs["name"]}


class _FakeDomainTableWriteService:
    def __init__(self):
        self.calls = []

    def add_or_update_table(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True}


class _FakeDomainJoinService:
    def __init__(self):
        self.calls = []

    def create_join(self, **kwargs):
        self.calls.append(kwargs)
        return {"ok": True, "id": str(len(self.calls))}


def test_generate_recommendations_normalizes_payload_and_flags_duplicates():
    sql = _FakeSql(
        [
            {
                "id": 1,
                "table_name": "dim_student",
                "full_name": "edfi_wh.dim_student",
                "description": "Student dimension",
            },
            {
                "id": 2,
                "table_name": "dim_student_school",
                "full_name": "edfi_wh.dim_student_school",
                "description": "Student school dimension",
            },
            {
                "id": 3,
                "table_name": "fct_student_school_association",
                "full_name": "edfi_wh.fct_student_school_association",
                "description": "Enrollment fact",
            },
        ]
    )
    llm = _FakeLlm(
        {
            "domains": [
                {
                    "name": "Student Demographics And Enrollment",
                    "description": "Core student identity and enrollment context.",
                    "table_names": [
                        "dim_student",
                        "dim_student_school",
                        "unknown_table",
                    ],
                    "confidence": 0.93,
                    "rationale": ["Student identity grain", "Enrollment context"],
                },
                {
                    "name": "Student Enrollment Duplicate",
                    "description": "Duplicate assignment to trigger warning.",
                    "table_names": [
                        "fct_student_school_association",
                        "dim_student",
                    ],
                    "confidence": 0.61,
                    "rationale": ["Shared student context"],
                },
            ],
            "unassigned_tables": [],
        }
    )

    payload = DomainRecommendationService(sql=sql, llm_client=llm).generate_recommendations(
        workspace_id="ws-1",
        max_domains=10,
        max_tables=200,
    )

    assert payload["workspace_id"] == "ws-1"
    assert len(payload["recommendations"]) == 2
    first = payload["recommendations"][0]
    second = payload["recommendations"][1]
    assert first["name"] == "Student Demographics And Enrollment"
    assert first["table_names"] == ["dim_student", "dim_student_school"]
    assert first["needs_review"] is True
    assert second["needs_review"] is True
    assert payload["unassigned_tables"] == []
    assert any("unknown tables" in warning for warning in payload["warnings"])
    assert any("assigned to multiple recommended domains" in warning for warning in payload["warnings"])


def test_generate_recommendations_returns_empty_payload_when_no_tables():
    payload = DomainRecommendationService(
        sql=_FakeSql([]),
        llm_client=_FakeLlm({"domains": []}),
    ).generate_recommendations(workspace_id="ws-empty")

    assert payload["workspace_id"] == "ws-empty"
    assert payload["recommendations"] == []
    assert payload["unassigned_tables"] == []
    assert payload["warnings"] == ["No workspace tables are available for this workspace."]


def test_apply_recommendations_creates_domains_and_assigns_tables():
    sql = _FakeSql(
        [
            {"id": 1, "table_name": "dim_student"},
            {"id": 2, "table_name": "dim_student_school"},
        ]
    )
    admin = _FakeDomainAdminWriteService()
    table_writer = _FakeDomainTableWriteService()
    svc = DomainRecommendationService(
        sql=sql,
        llm_client=_FakeLlm({"domains": []}),
        domain_admin_write_service=admin,
        domain_table_write_service=table_writer,
    )
    svc._load_domain_id_by_name = lambda **kwargs: None  # type: ignore[method-assign]

    out = svc.apply_recommendations(
        workspace_id="ws-1",
        user_id="user-1",
        recommendations=[
            {
                "name": "Student Demographics",
                "description": "Core student context",
                "table_names": ["dim_student", "dim_student_school"],
            }
        ],
        mode="create_only",
    )

    assert len(out["created_domains"]) == 1
    assert out["assigned_tables"] == 2
    assert admin.calls[0]["bypass_permissions"] is True
    assert table_writer.calls[0]["bypass_permissions"] is True


def test_apply_recommendations_creates_inferred_joins_for_shared_keys():
    sql = _FakeSql(
        [
            {"id": 1, "table_name": "dim_student"},
            {"id": 2, "table_name": "dim_student_school"},
            {"workspace_table_id": 1, "column_name": "student_id"},
            {"workspace_table_id": 1, "column_name": "student_name"},
            {"workspace_table_id": 2, "column_name": "student_id"},
            {"workspace_table_id": 2, "column_name": "school_id"},
        ]
    )
    join_writer = _FakeDomainJoinService()
    svc = DomainRecommendationService(
        sql=sql,
        llm_client=_FakeLlm({"domains": []}),
        domain_admin_write_service=_FakeDomainAdminWriteService(),
        domain_table_write_service=_FakeDomainTableWriteService(),
        domain_join_service=join_writer,
    )
    svc._load_domain_id_by_name = lambda **kwargs: None  # type: ignore[method-assign]

    out = svc.apply_recommendations(
        workspace_id="ws-1",
        user_id="user-1",
        recommendations=[
            {
                "name": "Student Domain",
                "table_names": ["dim_student", "dim_student_school"],
            }
        ],
    )

    assert out["created_joins"] == 1
    assert len(join_writer.calls) == 1
    assert join_writer.calls[0]["join_spec"]["on"][0]["left"]["columnName"] == "student_id"


def test_apply_recommendations_rejects_duplicate_tables_across_domains():
    svc = DomainRecommendationService(
        sql=_FakeSql([{"id": 1, "table_name": "dim_student"}]),
        llm_client=_FakeLlm({"domains": []}),
        domain_admin_write_service=_FakeDomainAdminWriteService(),
        domain_table_write_service=_FakeDomainTableWriteService(),
    )

    try:
        svc.apply_recommendations(
            workspace_id="ws-1",
            user_id="user-1",
            recommendations=[
                {"name": "Domain A", "table_names": ["dim_student"]},
                {"name": "Domain B", "table_names": ["dim_student"]},
            ],
        )
        assert False, "expected ForgeError"
    except Exception as exc:
        assert exc.__class__.__name__ == "ForgeError"
        assert "only be applied to one recommended domain" in str(exc)


def test_normalize_limit_surfaces_unexpected_int_errors() -> None:
    class _BadInt:
        def __int__(self) -> int:
            raise AssertionError("unexpected limit parse bug")

    with pytest.raises(AssertionError, match="unexpected limit parse bug"):
        DomainRecommendationService._normalize_limit(_BadInt(), field="max_tables", minimum=1, maximum=10)


def test_normalize_limit_wraps_expected_int_errors() -> None:
    with pytest.raises(ForgeError, match="max_tables must be an integer"):
        DomainRecommendationService._normalize_limit("bad", field="max_tables", minimum=1, maximum=10)
