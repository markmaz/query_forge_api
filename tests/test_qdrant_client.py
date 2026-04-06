from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from qdrant_client.http import models as qdrant_models

from app.infra.qdrant_client import QdrantClientWrapper


def test_ensure_payload_index_reraises_expected_runtime_errors() -> None:
    wrapper = QdrantClientWrapper(collection_name="table_catalog")
    wrapper._client = MagicMock()
    wrapper._client.create_payload_index.side_effect = RuntimeError("qdrant unavailable")

    with patch("app.infra.qdrant_client.logger.exception") as mock_log:
        with pytest.raises(RuntimeError, match="qdrant unavailable"):
            wrapper.ensure_payload_index(
                key="workspace_id",
                schema=qdrant_models.PayloadSchemaType.KEYWORD,
            )

    mock_log.assert_called_once()


def test_ensure_payload_index_surfaces_unexpected_assertion_errors() -> None:
    wrapper = QdrantClientWrapper(collection_name="table_catalog")
    wrapper._client = MagicMock()
    wrapper._client.create_payload_index.side_effect = AssertionError("unexpected qdrant bug")

    with patch("app.infra.qdrant_client.logger.exception") as mock_log:
        with pytest.raises(AssertionError, match="unexpected qdrant bug"):
            wrapper.ensure_payload_index(
                key="workspace_id",
                schema=qdrant_models.PayloadSchemaType.KEYWORD,
            )

    mock_log.assert_not_called()
