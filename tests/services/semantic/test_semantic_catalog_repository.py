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
