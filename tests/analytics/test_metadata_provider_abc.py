"""Verify MetadataProvider ABC cannot be instantiated and requires all methods."""
from __future__ import annotations

import pytest

from app.ports.metadata_provider_abc import MetadataProvider


def test_cannot_instantiate_abstract_class():
    with pytest.raises(TypeError):
        MetadataProvider()  # type: ignore[abstract]


def test_concrete_subclass_must_implement_all_methods():
    class _Incomplete(MetadataProvider):
        def list_tables(self, catalog, schema):
            return []
        # missing list_columns and profile_table_columns

    with pytest.raises(TypeError):
        _Incomplete()


def test_valid_concrete_subclass_instantiates():
    class _Concrete(MetadataProvider):
        def list_tables(self, catalog, schema):
            return []

        def list_columns(self, catalog, schema, table_names=None):
            return []

        def profile_table_columns(self, table_ref, columns, options):
            return {}

        def list_schemas(self, catalog):
            return []

    provider = _Concrete()
    assert provider.list_tables(None, "myschema") == []
