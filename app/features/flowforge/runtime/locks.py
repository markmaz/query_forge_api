from __future__ import annotations


class FlowForgeRuntimeLock:
    """Placeholder for a future DB/Valkey-backed runtime lock.

    Phase 11 keeps execution idempotent through durable event keys. Later phases
    should replace this no-op context manager with a real distributed lock before
    high-concurrency dispatch is enabled.
    """

    def __init__(self, *, workspace_id: str, run_id: int) -> None:
        self.workspace_id = workspace_id
        self.run_id = int(run_id)

    def __enter__(self) -> "FlowForgeRuntimeLock":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        del exc_type, exc, traceback
        return False
