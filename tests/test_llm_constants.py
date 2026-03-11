from app.constants.llm_roles import LLMRole, LLMProvider


def test_llm_role_all_contains_all_roles():
    assert LLMRole.PLANNER in LLMRole.ALL
    assert LLMRole.NER in LLMRole.ALL
    assert LLMRole.SUMMARIZER in LLMRole.ALL
    assert LLMRole.QUERY_GENERATOR in LLMRole.ALL
    assert LLMRole.ENRICHMENT in LLMRole.ALL
    assert len(LLMRole.ALL) == 5


def test_llm_provider_all_contains_supported_providers():
    assert LLMProvider.OPENAI in LLMProvider.ALL
    assert LLMProvider.ANTHROPIC in LLMProvider.ALL
    assert LLMProvider.AZURE_OPENAI in LLMProvider.ALL
    assert LLMProvider.OLLAMA in LLMProvider.ALL
    assert LLMProvider.GENERIC in LLMProvider.ALL
    assert len(LLMProvider.ALL) == 5
