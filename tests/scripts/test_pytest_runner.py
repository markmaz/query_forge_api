from __future__ import annotations

import os
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "scripts" / "pytest.sh"


def test_pytest_runner_uses_explicit_binary_override(tmp_path: Path) -> None:
    output_path = tmp_path / "args.txt"
    fake_pytest = tmp_path / "fake-pytest.sh"
    fake_pytest.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$@\" > \"$OUTPUT_PATH\"\n"
    )
    fake_pytest.chmod(0o755)

    result = subprocess.run(
        [str(RUNNER), "-q", "tests/example_test.py::test_demo"],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "QF_PYTEST": str(fake_pytest),
            "OUTPUT_PATH": str(output_path),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert output_path.read_text().splitlines() == ["-q", "tests/example_test.py::test_demo"]


def test_pytest_runner_fails_when_binary_is_missing(tmp_path: Path) -> None:
    missing_binary = tmp_path / "missing-pytest"

    result = subprocess.run(
        [str(RUNNER), "-q"],
        cwd=REPO_ROOT,
        env={**os.environ, "QF_PYTEST": str(missing_binary)},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "project virtualenv" in result.stderr
    assert ".venv/bin/pytest" in result.stderr
