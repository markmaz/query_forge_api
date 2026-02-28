#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


DEFAULT_CONFIG = "app/nlp/tier2_spacy/config/config_ner_only.cfg"


def _config_uses_transformer(config_path: str) -> bool:
    try:
        text = Path(config_path).read_text(encoding="utf-8")
    except Exception:
        return False
    return 'factory = "transformer"' in text or "pipeline = [\"transformer\"" in text


def _check_transformer_dependency(config_path: str) -> bool:
    if not _config_uses_transformer(config_path):
        return True
    try:
        import spacy_transformers  # noqa: F401
    except Exception:
        print(
            "ERROR: This config uses a 'transformer' component, but 'spacy-transformers' "
            "is not installed in the active environment."
        )
        print("Install it with:")
        print(f"  {sys.executable} -m pip install spacy-transformers torch")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Train Tier2 spaCy transformer pipeline")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="spaCy config path")
    parser.add_argument("--train", required=True, help="Train .spacy file")
    parser.add_argument("--dev", required=True, help="Dev .spacy file")
    parser.add_argument("--output", required=True, help="Output model directory")
    parser.add_argument("--gpu", type=int, default=-1, help="GPU id (default CPU)")
    parser.add_argument(
        "--cpu-only",
        action="store_true",
        help="Force CPU training; ignores --gpu if provided",
    )
    args = parser.parse_args()

    if not _check_transformer_dependency(args.config):
        return 2

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "spacy",
        "train",
        args.config,
        "--paths.train",
        args.train,
        "--paths.dev",
        args.dev,
        "--output",
        str(output_dir),
    ]
    if args.cpu_only:
        if args.gpu >= 0:
            print("Ignoring --gpu because --cpu-only is set.")
    elif args.gpu >= 0:
        cmd.extend(["--gpu-id", str(args.gpu)])

    print("Running:", " ".join(cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
