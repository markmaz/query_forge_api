from __future__ import annotations

import app.tasks.logging_tasks as logging_tasks


def test_persist_log_default():
    assert logging_tasks.persist_log() is None
