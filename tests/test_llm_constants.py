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


def test_llm_role_display_names_in_sync_with_all():
    assert set(LLMRole.DISPLAY_NAMES.keys()) == set(LLMRole.ALL)
    for role in LLMRole.ALL:
        assert isinstance(LLMRole.DISPLAY_NAMES[role], str)
        assert len(LLMRole.DISPLAY_NAMES[role]) > 0


def test_llm_provider_display_names_in_sync_with_all():
    assert set(LLMProvider.DISPLAY_NAMES.keys()) == set(LLMProvider.ALL)
    for provider in LLMProvider.ALL:
        assert isinstance(LLMProvider.DISPLAY_NAMES[provider], str)
        assert len(LLMProvider.DISPLAY_NAMES[provider]) > 0
