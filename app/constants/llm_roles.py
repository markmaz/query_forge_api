from __future__ import annotations


class LLMRole:
    PLANNER = "planner"
    NER = "ner"
    SUMMARIZER = "summarizer"
    QUERY_GENERATOR = "query_generator"
    ENRICHMENT = "enrichment"
    FLOWFORGE_RULE_DRAFTING = "flowforge_rule_drafting"

    ALL = (PLANNER, NER, SUMMARIZER, QUERY_GENERATOR, ENRICHMENT, FLOWFORGE_RULE_DRAFTING)

    DISPLAY_NAMES = {
        PLANNER: "Planner",
        NER: "Named Entity Recognition",
        SUMMARIZER: "Summarizer",
        QUERY_GENERATOR: "Query Generator",
        ENRICHMENT: "Enrichment",
        FLOWFORGE_RULE_DRAFTING: "FlowForge Rule Drafting",
    }


class LLMProvider:
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE_OPENAI = "azure_openai"
    OLLAMA = "ollama"
    GENERIC = "generic"

    ALL = (OPENAI, ANTHROPIC, AZURE_OPENAI, OLLAMA, GENERIC)

    DISPLAY_NAMES = {
        OPENAI: "OpenAI",
        ANTHROPIC: "Anthropic",
        AZURE_OPENAI: "Azure OpenAI",
        OLLAMA: "Ollama (local)",
        GENERIC: "Generic (OpenAI-compatible)",
    }
