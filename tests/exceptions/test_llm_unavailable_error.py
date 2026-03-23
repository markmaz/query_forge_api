from __future__ import annotations


def test_import_and_raise():
    from app.exceptions.llm_unavailable_error import LLMUnavailableError
    err = LLMUnavailableError("no llm configured")
    assert isinstance(err, Exception)
    assert "no llm configured" in str(err)


def test_is_not_forge_error():
    from app.exceptions.llm_unavailable_error import LLMUnavailableError
    from app.exceptions.forge_error import ForgeError
    assert not issubclass(LLMUnavailableError, ForgeError)
