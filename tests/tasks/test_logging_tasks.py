from __future__ import annotations

import app.tasks.logging_tasks as logging_tasks


def test_flush_query_log_default():
    assert logging_tasks.flush_query_log() is None
