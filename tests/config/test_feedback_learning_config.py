from __future__ import annotations

from app.config.feedback_learning_config import load_feedback_learning_config


def test_feedback_learning_config_uses_defaults_when_env_missing(monkeypatch) -> None:
    monkeypatch.delenv("FEEDBACK_AUTO_APPLY_ENABLED", raising=False)
    monkeypatch.delenv("FEEDBACK_CONFIDENCE_THRESHOLD", raising=False)
    monkeypatch.delenv("FEEDBACK_EVIDENCE_THRESHOLD", raising=False)
    monkeypatch.delenv("FEEDBACK_EVALUATOR_MAX_RETRIES", raising=False)
    monkeypatch.delenv("FEEDBACK_WORKSPACE_OVERRIDES_ENABLED", raising=False)
    monkeypatch.delenv("FEEDBACK_DOMAIN_EXAMPLE_CONFIDENCE_THRESHOLD", raising=False)

    config = load_feedback_learning_config()

    assert config.auto_apply_enabled is True
    assert config.confidence_threshold == 0.85
    assert config.evidence_threshold == 3
    assert config.evaluator_max_retries == 2
    assert config.workspace_overrides_enabled is True
    assert config.domain_example_confidence_threshold == 0.90


def test_feedback_learning_config_normalizes_invalid_thresholds(monkeypatch) -> None:
    monkeypatch.setenv("FEEDBACK_AUTO_APPLY_ENABLED", "0")
    monkeypatch.setenv("FEEDBACK_CONFIDENCE_THRESHOLD", "0.92")
    monkeypatch.setenv("FEEDBACK_EVIDENCE_THRESHOLD", "-4")
    monkeypatch.setenv("FEEDBACK_EVALUATOR_MAX_RETRIES", "-1")
    monkeypatch.setenv("FEEDBACK_WORKSPACE_OVERRIDES_ENABLED", "false")
    monkeypatch.setenv("FEEDBACK_DOMAIN_EXAMPLE_CONFIDENCE_THRESHOLD", "0.975")

    config = load_feedback_learning_config()

    assert config.auto_apply_enabled is False
    assert config.confidence_threshold == 0.92
    assert config.evidence_threshold == 1
    assert config.evaluator_max_retries == 0
    assert config.workspace_overrides_enabled is False
    assert config.domain_example_confidence_threshold == 0.975
