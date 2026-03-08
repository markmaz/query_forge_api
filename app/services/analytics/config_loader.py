from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Default path relative to the project root (query-forge-api/)
_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "analytics_datasources.yaml"

# Pattern for ${ENV_VAR} substitution
_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")

# Required keys per datasource type
_REQUIRED_KEYS: dict[str, list[str]] = {
    "databricks": ["host", "token", "http_path"],
    "snowflake": ["account", "user", "database", "warehouse"],
    # FIND-022: ssl_ca is required for MySQL analytics connections.
    "mysql": ["host", "database", "user", "password", "ssl_ca"],
}


def _resolve_env_vars(value: Any) -> Any:
    """Recursively resolve ``${ENV_VAR}`` patterns in string values.

    Non-string values are returned unchanged.  If a referenced environment variable
    is not set, the placeholder is left as-is (empty string substitution is intentionally
    avoided to preserve explicit missing-variable detection).

    :param value: The config value to process.
    :returns: Processed value with env var references expanded.
    """
    if isinstance(value, str):
        def _replace(match: re.Match) -> str:  # type: ignore[type-arg]
            var_name = match.group(1)
            env_value = os.environ.get(var_name)
            if env_value is None:
                # Return the original placeholder — validation will catch missing vars
                return match.group(0)
            return env_value

        return _ENV_VAR_RE.sub(_replace, value)

    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}

    if isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]

    return value


def _find_unresolved_placeholders(config: dict[str, Any]) -> list[str]:
    """Return a list of ``${VAR}`` placeholder strings still present after resolution."""
    unresolved: list[str] = []

    def _scan(value: Any, path: str) -> None:
        if isinstance(value, str):
            for match in _ENV_VAR_RE.finditer(value):
                unresolved.append(f"{path}: {match.group(0)}")
        elif isinstance(value, dict):
            for k, v in value.items():
                _scan(v, f"{path}.{k}")
        elif isinstance(value, list):
            for i, item in enumerate(value):
                _scan(item, f"{path}[{i}]")

    for ds_name, ds_cfg in config.items():
        _scan(ds_cfg, ds_name)

    return unresolved


def _validate_datasource(name: str, cfg: dict[str, Any]) -> None:
    """Validate that a single datasource config has the required keys for its type.

    :param name: Datasource name (used in error messages).
    :param cfg: Datasource config dict (after env var resolution).
    :raises ValueError: if ``type`` is missing, unknown, or required keys are absent.
    """
    ds_type = (cfg.get("type") or "").strip().lower()
    if not ds_type:
        raise ValueError(f"Datasource '{name}' is missing required key 'type'")

    required = _REQUIRED_KEYS.get(ds_type)
    if required is None:
        raise ValueError(
            f"Datasource '{name}' has unknown type '{ds_type}'. "
            f"Supported: {sorted(_REQUIRED_KEYS)}"
        )

    missing = [k for k in required if not cfg.get(k)]
    if missing:
        raise ValueError(
            f"Datasource '{name}' (type={ds_type}) is missing required keys: {missing}"
        )


def load_analytics_config(config_path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load and return the analytics datasource configuration.

    Reads ``config/analytics_datasources.yaml``, resolves ``${ENV_VAR}`` placeholders
    using ``os.environ``, and validates required fields per datasource type.

    :param config_path: Override the default config file path.  Useful in tests.
    :returns: Dict mapping datasource name → config dict (with ``type`` key present).
    :raises FileNotFoundError: if the config file does not exist.
    :raises ValueError: if any datasource config is invalid or env vars are unresolved.
    """
    path = config_path or _DEFAULT_CONFIG_PATH

    if not Path(path).exists():
        raise FileNotFoundError(f"Analytics datasource config not found: {path}")

    logger.debug("Loading analytics datasource config from %s", path)

    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    datasources_raw: dict[str, Any] = raw.get("analytics_datasources") or {}
    if not datasources_raw:
        logger.warning("analytics_datasources.yaml contains no datasource definitions")
        return {}

    resolved: dict[str, dict[str, Any]] = _resolve_env_vars(datasources_raw)  # type: ignore[assignment]

    # Detect unresolved placeholders — log a warning per missing variable but do not raise,
    # so that partially configured environments can still start (individual lookups will fail).
    unresolved = _find_unresolved_placeholders(resolved)
    for placeholder in unresolved:
        logger.warning("Unresolved env var in analytics config: %s", placeholder)

    # Validate structure — raises ValueError on schema errors
    for ds_name, ds_cfg in resolved.items():
        if not isinstance(ds_cfg, dict):
            raise ValueError(f"Datasource '{ds_name}' config must be a mapping, got {type(ds_cfg)}")
        _validate_datasource(ds_name, ds_cfg)

    logger.info(
        "Loaded %d analytics datasource(s): %s",
        len(resolved),
        ", ".join(
            f"{name}({cfg.get('type', '?')})" for name, cfg in resolved.items()
        ),
    )

    return resolved
