from __future__ import annotations

import importlib
import os

import app.config as config_module


def test_config_reads_smtp_port_env_var() -> None:
    original_smtp_port = os.environ.get("SMTP_PORT")
    original_smpt_port = os.environ.get("SMPT_PORT")

    try:
        os.environ["SMTP_PORT"] = "2525"
        os.environ.pop("SMPT_PORT", None)

        reloaded = importlib.reload(config_module)

        assert reloaded.SMTP_PORT == "2525"
    finally:
        if original_smtp_port is None:
            os.environ.pop("SMTP_PORT", None)
        else:
            os.environ["SMTP_PORT"] = original_smtp_port
        if original_smpt_port is None:
            os.environ.pop("SMPT_PORT", None)
        else:
            os.environ["SMPT_PORT"] = original_smpt_port
        importlib.reload(config_module)

