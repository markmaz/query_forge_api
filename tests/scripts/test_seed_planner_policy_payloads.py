from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts/seed_planner_policy_payloads.py"
)

spec = importlib.util.spec_from_file_location(
    "seed_planner_policy_payloads",
    SCRIPT_PATH,
)
seed_module = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
spec.loader.exec_module(seed_module)


def test_load_seed_document_reads_expected_counts() -> None:
    document = seed_module.load_seed_document(seed_module.DEFAULT_PAYLOAD_PATH)

    assert document["total_payload_count"] == 114
    families = {item["family_key"]: item for item in document["families"]}
    assert families["planner_signal_policy"]["count"] == 31
    assert families["planner_semantic_time_policy"]["count"] == 2


def test_select_families_preserves_requested_order() -> None:
    document = seed_module.load_seed_document(seed_module.DEFAULT_PAYLOAD_PATH)

    families = seed_module.select_families(
        document,
        ["planner_retrieval_policy", "planner_signal_policy"],
    )

    assert [item["family_key"] for item in families] == [
        "planner_retrieval_policy",
        "planner_signal_policy",
    ]


def test_build_db_params_normalizes_booleans_and_projection_scope() -> None:
    payload = {
        "policy_key": "example_projection",
        "name": "Example Projection",
        "description": "Example description",
        "scope_type": "workspace_domain",
        "scope_workspace_id": "ws_123",
        "scope_base_domain_id": 77,
        "priority": 125,
        "is_active": True,
        "stop_on_match": False,
        "policy_json": {"version": 1, "projection_mode": "prepend"},
    }

    params = seed_module.build_db_params(payload)

    assert params["scope_base_domain_id"] == 77
    assert params["is_active"] == 1
    assert params["stop_on_match"] == 0
    assert '"projection_mode": "prepend"' in params["policy_json"]


def test_resolve_db_uri_prefers_flag_overrides(monkeypatch) -> None:
    monkeypatch.setenv("DB_HOST", "env-host")
    monkeypatch.setenv("DB_USER", "env-user")
    monkeypatch.setenv("DB_PASSWORD", "env-pass")
    monkeypatch.setenv("DB_NAME", "env-db")
    monkeypatch.setenv("DB_PORT", "3307")
    monkeypatch.delenv("DB_URI", raising=False)

    uri = seed_module._resolve_db_uri(
        {
            "host": "flag-host",
            "user": "flag-user",
            "password": "flag-pass",
            "database": "flag-db",
            "port": "3308",
        }
    )

    assert uri.startswith("mysql+pymysql://flag-user:")
    assert "@flag-host:3308/flag-db" in uri
