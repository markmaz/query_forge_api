from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts/run_feedback_analysis_backfill.py"
)
spec = importlib.util.spec_from_file_location(
    "run_feedback_analysis_backfill",
    SCRIPT_PATH,
)
backfill_module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(backfill_module)


class _Service:
    def __init__(self):
        self.calls = []

    def backfill_negative_feedback(self, *, limit=None, dry_run=True, workspace_id=None, date_from=None, date_to=None):
        self.calls.append(
            {
                "limit": limit,
                "dry_run": dry_run,
                "workspace_id": workspace_id,
                "date_from": date_from,
                "date_to": date_to,
            }
        )
        return {"dry_run": dry_run, "identified_count": 2, "analyzed_count": 0 if dry_run else 2}


def test_main_defaults_to_dry_run(monkeypatch, capsys) -> None:
    service = _Service()
    monkeypatch.setattr(backfill_module, "AnalysisBackfillService", lambda: service)

    exit_code = backfill_module.main(["--limit", "25", "--workspace-id", "ws-1"])

    assert exit_code == 0
    assert service.calls == [
        {
            "limit": 25,
            "dry_run": True,
            "workspace_id": "ws-1",
            "date_from": None,
            "date_to": None,
        }
    ]
    assert "identified_count" in capsys.readouterr().out


def test_main_write_flag_runs_live_backfill(monkeypatch) -> None:
    service = _Service()
    monkeypatch.setattr(backfill_module, "AnalysisBackfillService", lambda: service)

    exit_code = backfill_module.main(
        ["--limit", "10", "--write", "--date-from", "2026-04-01", "--date-to", "2026-04-30"]
    )

    assert exit_code == 0
    assert service.calls == [
        {
            "limit": 10,
            "dry_run": False,
            "workspace_id": None,
            "date_from": "2026-04-01",
            "date_to": "2026-04-30",
        }
    ]
