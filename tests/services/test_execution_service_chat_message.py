from app.services.execution_service import _build_assistant_result_message


def test_build_assistant_result_message_includes_markdown_table() -> None:
    msg = _build_assistant_result_message(
        rows=[{"school_name": "Barksdale Elementary", "students": 120}],
        columns=[{"key": "school_name"}, {"key": "students"}],
        total=1,
        limit=200,
        offset=0,
    )
    assert msg["role"] == "assistant"
    assert msg["kind"] == "execution_result"
    assert msg["format"] == "markdown"
    content = str(msg["content"])
    assert "Query complete." in content
    assert "| school_name | students |" in content
    assert "Barksdale Elementary" in content
