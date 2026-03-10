from __future__ import annotations

from unittest.mock import MagicMock

from app.services.analytics.dictionary_llm_adapter import DictionaryLLMAdapter


def test_generate_returns_description_from_llm_payload():
    llm = MagicMock()
    llm.chat_json.return_value = {"description": "A short description."}
    adapter = DictionaryLLMAdapter(llm_client=llm)

    result = adapter.generate("describe this column")

    assert result == "A short description."
    llm.chat_json.assert_called_once()

