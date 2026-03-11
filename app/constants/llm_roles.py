from __future__ import annotations


class LLMRole:
    PLANNER = "planner"
    NER = "ner"
    SUMMARIZER = "summarizer"
    QUERY_GENERATOR = "query_generator"
    ENRICHMENT = "enrichment"

    ALL = [PLANNER, NER, SUMMARIZER, QUERY_GENERATOR, ENRICHMENT]

    DISPLAY_NAMES = {
        PLANNER: "Planner",
        NER: "Named Entity Recognition",
        SUMMARIZER: "Summarizer",
        QUERY_GENERATOR: "Query Generator",
        ENRICHMENT: "Enrichment",
    }


class LLMProvider:
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE_OPENAI = "azure_openai"
    OLLAMA = "ollama"
    GENERIC = "generic"

    ALL = [OPENAI, ANTHROPIC, AZURE_OPENAI, OLLAMA, GENERIC]

    DISPLAY_NAMES = {
        OPENAI: "OpenAI",
        ANTHROPIC: "Anthropic",
        AZURE_OPENAI: "Azure OpenAI",
        OLLAMA: "Ollama (local)",
        GENERIC: "Generic (OpenAI-compatible)",
    }
