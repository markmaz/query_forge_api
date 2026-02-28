#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Package Tier2 spaCy model")
    parser.add_argument("--model-dir", required=True, help="Path to trained model-best/model-last directory")
    parser.add_argument("--output", required=True, help="Package output directory")
    parser.add_argument("--name", default="query_forge_tier2", help="Python package name")
    parser.add_argument("--version", default="0.1.0", help="Package version")
    parser.add_argument("--build", action="store_true", help="Build wheel/sdist")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "python",
        "-m",
        "spacy",
        "package",
        args.model_dir,
        str(output_dir),
        "--name",
        args.name,
        "--version",
        args.version,
    ]
    if args.build:
        cmd.append("--build")

    print("Running:", " ".join(cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
