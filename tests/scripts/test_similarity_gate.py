from __future__ import annotations

import json
from pathlib import Path

from scripts import similarity_gate


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_compare_repositories_counts_exact_and_normalized(tmp_path: Path) -> None:
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    _write(src / "app/services/a.py", "def f():\n    return 1\n")
    _write(tgt / "app/services/a.py", "def f():\n    return 1\n")

    # raw differs due to comment, normalized should match
    _write(src / "app/services/b.py", "def g():\n    # source comment\n    return 2\n")
    _write(tgt / "app/services/b.py", "def g():\n    # target comment\n    return 2\n")

    report = similarity_gate.compare_repositories(src, tgt)
    pct = report["percentages"]
    assert report["counts"]["files_source"] == 2
    assert pct["exact_match_anywhere_pct_of_source"] == 50.0
    assert pct["normalized_exact_anywhere_pct_of_source"] == 100.0


def test_collect_signatures_excludes_noise_dirs(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _write(root / "app/services/ok.py", "print('ok')\n")
    _write(root / ".venv/lib/skip.py", "print('skip')\n")
    _write(root / "data/skip.py", "print('skip')\n")
    _write(root / "models/skip.py", "print('skip')\n")

    sig = similarity_gate.collect_signatures(root)
    assert "app/services/ok.py" in sig
    assert ".venv/lib/skip.py" not in sig
    assert "data/skip.py" not in sig
    assert "models/skip.py" not in sig


def test_threshold_evaluation_flags_failures(tmp_path: Path) -> None:
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    _write(src / "app/services/a.py", "def f():\n    return 1\n")
    _write(tgt / "app/services/a.py", "def f():\n    return 1\n")
    report = similarity_gate.compare_repositories(src, tgt)

    failures = similarity_gate.evaluate_thresholds(
        report,
        exact_max_pct=10.0,
        normalized_exact_max_pct=10.0,
        line_overlap_max_pct=10.0,
    )
    assert failures
    assert any("exact_match_anywhere_pct_of_source" in msg for msg in failures)


def test_cli_main_writes_json_and_returns_nonzero_on_failure(tmp_path: Path) -> None:
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    out_json = tmp_path / "report" / "sim.json"
    _write(src / "app/services/a.py", "def f():\n    return 1\n")
    _write(tgt / "app/services/a.py", "def f():\n    return 1\n")

    code = similarity_gate.main(
        [
            "--source-repo",
            str(src),
            "--target-repo",
            str(tgt),
            "--exact-max-pct",
            "0.0",
            "--output-json",
            str(out_json),
        ]
    )
    assert code == 1
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["threshold_failures"]
    assert payload["report"]["counts"]["files_source"] == 1
