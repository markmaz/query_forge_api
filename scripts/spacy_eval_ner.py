#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _print_summary(payload: Dict[str, Any]) -> None:
    ents_f = _safe_float(payload.get("ents_f"))
    ents_p = _safe_float(payload.get("ents_p"))
    ents_r = _safe_float(payload.get("ents_r"))
    print(f"ents_f={ents_f:.4f} ents_p={ents_p:.4f} ents_r={ents_r:.4f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate spaCy NER model and print ents_f/p/r summary.")
    parser.add_argument("--model", required=True, help="Model path (e.g., models/tier2/model-best)")
    parser.add_argument("--data", required=True, help="Evaluation DocBin path (e.g., data/dev.spacy)")
    parser.add_argument("--out", required=True, help="Output JSON path for spaCy evaluate results")
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "spacy",
        "evaluate",
        str(args.model),
        str(args.data),
        "--output",
        str(out_path),
    ]
    print("Running:", " ".join(cmd))

    try:
        subprocess.run(cmd, check=False)
    except Exception as exc:
        print(f"WARN: failed to run spacy evaluate: {exc}")
        return 0

    if not out_path.exists():
        print(f"WARN: evaluation output file was not created: {out_path}")
        return 0

    try:
        payload = json.loads(out_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"WARN: could not parse evaluation output JSON: {exc}")
        return 0

    _print_summary(payload if isinstance(payload, dict) else {})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

