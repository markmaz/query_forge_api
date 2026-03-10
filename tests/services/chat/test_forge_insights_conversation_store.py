from __future__ import annotations

from datetime import datetime

from app.ports.sql_executor import ForgeExecResult
from app.services.chat.forge_insights_conversation_store import ForgeInsightsConversationStore
from tests._support.fakes import FakeForgeQueryPort


def test_save_conversation_upserts_and_rewrites_messages() -> None:
    sql = FakeForgeQueryPort()
    sql.insert_responses = [ForgeExecResult(rowcount=1, lastrowid=101)]
    store = ForgeInsightsConversationStore(sql=sql)

    store.save_conversation(
        workspace_id="ws-1",
        user_id="user-1",
        conversation_id="fi_abc",
        conversation={
            "title": "Show me staff",
            "summary": "Some summary",
            "messages": [
                {"role": "user", "content": "Show me staff at Barksdale"},
                {"role": "assistant", "content": "Here are staff"},
            ],
        },
        qf_ttl_seconds=999,
    )

    assert len(sql.insert_calls) == 1
    assert "forge_insights_conversation" in sql.insert_calls[0].query
    assert sql.insert_calls[0].params["conversation_id"] == "fi_abc"
    assert len(sql.write_calls) == 3
    assert "DELETE FROM forge_insights_message" in sql.write_calls[0].query
    assert sql.write_calls[0].params["conversation_pk"] == 101
    assert sql.write_calls[1].params["seq_no"] == 1
    assert sql.write_calls[1].params["role"] == "user"
    assert sql.write_calls[2].params["seq_no"] == 2
    assert sql.write_calls[2].params["role"] == "assistant"


def test_get_conversation_returns_messages_and_metadata() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": 55,
                "workspace_id": "ws-1",
                "user_id": "user-1",
                "conversation_id": "fi_55",
                "title": "Show students",
                "summary": "Student summary",
                "message_count": 2,
                "created_at": datetime(2026, 3, 3, 1, 0, 0),
                "updated_at": datetime(2026, 3, 3, 1, 2, 0),
                "last_message_at": datetime(2026, 3, 3, 1, 2, 0),
            }
        ],
        [
            {"role": "user", "content": "Show students"},
            {"role": "assistant", "content": "Done"},
        ],
    ]
    store = ForgeInsightsConversationStore(sql=sql)

    out = store.get_conversation(workspace_id="ws-1", user_id="user-1", conversation_id="fi_55")
    assert out is not None
    assert out["conversation_id"] == "fi_55"
    assert out["message_count"] == 2
    assert out["last_user_message"] == "Show students"
    assert len(out["messages"]) == 2
    assert out["messages"][0]["role"] == "user"


def test_list_conversations_reads_from_db_and_includes_last_user_message() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [
        [
            {
                "id": 11,
                "conversation_id": "fi_11",
                "title": "Thread 1",
                "summary": "Has summary",
                "message_count": 6,
                "created_at": datetime(2026, 3, 3, 2, 0, 0),
                "updated_at": datetime(2026, 3, 3, 2, 2, 0),
                "last_message_at": datetime(2026, 3, 3, 2, 2, 0),
            },
            {
                "id": 12,
                "conversation_id": "fi_12",
                "title": "Thread 2",
                "summary": "",
                "message_count": 4,
                "created_at": datetime(2026, 3, 3, 2, 10, 0),
                "updated_at": datetime(2026, 3, 3, 2, 11, 0),
                "last_message_at": datetime(2026, 3, 3, 2, 11, 0),
            },
        ],
        [{"content": "latest user prompt"}],
        [],
    ]
    store = ForgeInsightsConversationStore(sql=sql)

    rows = store.list_conversations(workspace_id="ws-1", user_id="user-1", limit=10)
    assert len(rows) == 2
    assert rows[0]["conversation_id"] == "fi_11"
    assert rows[0]["last_user_message"] == "latest user prompt"
    assert rows[0]["has_summary"] is True
    assert rows[1]["has_summary"] is False


def test_delete_conversation_returns_false_when_missing() -> None:
    sql = FakeForgeQueryPort()
    sql.query_mappings_responses = [[]]
    store = ForgeInsightsConversationStore(sql=sql)

    deleted = store.delete_conversation(workspace_id="ws-1", user_id="user-1", conversation_id="fi_missing")
    assert deleted is False
    assert sql.write_calls == []
