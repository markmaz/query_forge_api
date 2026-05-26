from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts/promote_override.py"
spec = importlib.util.spec_from_file_location("promote_override", SCRIPT_PATH)
promote_module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(promote_module)


class _Service:
    def __init__(self):
        self.calls = []

    def promote_semantic_override(self, *, override_id: int, promoted_by: str, notes=None):
        self.calls.append(("semantic", override_id, promoted_by, notes))
        return {"promotion_status": "succeeded"}

    def promote_domain_override(self, *, override_id: int, promoted_by: str, notes=None):
        self.calls.append(("domain", override_id, promoted_by, notes))
        return {"promotion_status": "succeeded"}


def test_main_dispatches_semantic_promotion(monkeypatch, capsys) -> None:
    service = _Service()
    monkeypatch.setattr(promote_module, "CatalogPromotionService", lambda: service)

    exit_code = promote_module.main(
        ["--kind", "semantic", "--override-id", "12", "--promoted-by", "admin-1", "--notes", "approved"]
    )

    assert exit_code == 0
    assert service.calls == [("semantic", 12, "admin-1", "approved")]
    assert "succeeded" in capsys.readouterr().out


def test_main_dispatches_domain_promotion(monkeypatch, capsys) -> None:
    service = _Service()
    monkeypatch.setattr(promote_module, "CatalogPromotionService", lambda: service)

    exit_code = promote_module.main(
        ["--kind", "domain", "--override-id", "14", "--promoted-by", "admin-1"]
    )

    assert exit_code == 0
    assert service.calls == [("domain", 14, "admin-1", None)]
    assert "succeeded" in capsys.readouterr().out

