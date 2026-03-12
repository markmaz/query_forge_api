from __future__ import annotations

from pathlib import Path

import pytest

from app.exceptions.forge_error import ForgeError
from app.services.version_service import VersionService


def test_get_version_payload_from_object(tmp_path: Path) -> None:
    version_file = tmp_path / "version.json"
    version_file.write_text('{"version":"2.0.1","build":"abc123"}', encoding="utf-8")

    out = VersionService(version_file=version_file).get_version_payload()
    assert out["version"] == "2.0.1"
    assert out["build"] == "abc123"


def test_get_version_payload_from_string(tmp_path: Path) -> None:
    version_file = tmp_path / "version.json"
    version_file.write_text('"3.4.5"', encoding="utf-8")

    out = VersionService(version_file=version_file).get_version_payload()
    assert out == {"version": "3.4.5"}


def test_get_version_payload_missing_file(tmp_path: Path) -> None:
    version_file = tmp_path / "missing.json"
    with pytest.raises(ForgeError) as exc_info:
        VersionService(version_file=version_file).get_version_payload()
    assert exc_info.value.status_code == 500


def test_get_version_payload_invalid_json(tmp_path: Path) -> None:
    version_file = tmp_path / "version.json"
    version_file.write_text("{bad-json", encoding="utf-8")
    with pytest.raises(ForgeError) as exc_info:
        VersionService(version_file=version_file).get_version_payload()
    assert exc_info.value.status_code == 500

