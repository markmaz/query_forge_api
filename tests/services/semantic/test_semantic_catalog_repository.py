from __future__ import annotations

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.services.semantic.catalog.semantic_catalog_repository import SemanticCatalogRepository
from tests._support.fakes import FakeForgeQueryPort


def test_get_relationship_fk_target_falls_back_on_expected_lookup_errors() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_exceptions = [SQLAlchemyError("information schema unavailable")]

    repo = SemanticCatalogRepository(sql=sql)

    assert repo._get_relationship_fk_target() == "semantic_concept"


def test_get_relationship_fk_target_surfaces_unexpected_lookup_errors() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_exceptions = [AssertionError("unexpected fk target bug")]

    repo = SemanticCatalogRepository(sql=sql)

    with pytest.raises(AssertionError, match="unexpected fk target bug"):
        repo._get_relationship_fk_target()


def test_get_concepts_queries_by_concept_key_only() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[]]
    repo = SemanticCatalogRepository(sql=sql)

    out = repo.get_concepts(concept_keys=["STUDENT_ID"])

    assert out == []
    assert "vertical_norm" not in (sql.query_mappings_calls[0].params or {})


def test_get_aliases_by_concept_keys_queries_by_concept_key_only() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[]]
    repo = SemanticCatalogRepository(sql=sql)

    out = repo.get_aliases_by_concept_keys(concept_keys=["STUDENT_ID"])

    assert out == {}
    assert "vertical_norm" not in (sql.query_mappings_calls[0].params or {})
