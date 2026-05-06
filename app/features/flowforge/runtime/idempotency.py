from __future__ import annotations


def dispatch_event_key(*, run_id: int, suffix: str) -> str:
    return f"flowforge:run:{int(run_id)}:dispatch:{suffix}"


def node_event_key(*, run_id: int, node_id: str, suffix: str) -> str:
    return f"flowforge:run:{int(run_id)}:node:{str(node_id or '').strip()}:{suffix}"
