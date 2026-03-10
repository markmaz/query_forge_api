#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Mapping, Sequence

DEFAULT_INCLUDE_EXTENSIONS = {
    ".py",
    ".sql",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".sh",
}
DEFAULT_ALLOWED_PREFIXES = (
    "app/",
    "db/migrations/",
    "scripts/",
    "wsgi.py",
    "pyproject.toml",
    "requirements.txt",
)
DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".hypothesis",
    "node_modules",
    "logs",
    "data",
    "models",
    "infra/qdrant/storage",
    "workboard_api.egg-info",
    "requirements",
}
DEFAULT_EXCLUDE_PATTERNS = (
    re.compile(r"(^|/)log_file$"),
    re.compile(r"(^|/).*\.coverage$"),
    re.compile(r"(^|/)coverage\.(xml|json)$"),
    re.compile(r"(^|/)query-forge_dump_.*\.sql$"),
    re.compile(r"(^|/)tree\.txt$"),
    re.compile(r"(^|/).*\.pyc$"),
)


@dataclass(frozen=True)
class FileSignature:
    relative_path: str
    normalized_text: str
    normalized_lines: tuple[str, ...]
    raw_hash: str | None
    normalized_hash: str | None


def normalize_lines(text: str, extension: str) -> list[str]:
    normalized: list[str] = []
    content = text.replace("\r\n", "\n").replace("\r", "\n")
    for line in content.split("\n"):
        token = line.strip()
        if not token:
            continue
        if extension in {".py", ".sh", ".yml", ".yaml", ".toml", ".ini", ".cfg"} and token.startswith("#"):
            continue
        if extension == ".sql" and token.startswith("--"):
            continue
        if token.startswith("//"):
            continue
        token = re.sub(r"\s+", " ", token).strip().lower()
        if token:
            normalized.append(token)
    return normalized


def _is_excluded(
    relative_path: str,
    *,
    allowed_prefixes: Sequence[str],
    excluded_dirs: set[str],
    exclude_patterns: Sequence[re.Pattern[str]],
) -> bool:
    rel = relative_path.replace("\\", "/")
    if not rel.startswith(tuple(allowed_prefixes)):
        return True
    parts = rel.split("/")
    for idx, segment in enumerate(parts):
        partial = "/".join(parts[: idx + 1])
        if segment in excluded_dirs or partial in excluded_dirs:
            return True
    return any(p.search("/" + rel) for p in exclude_patterns)


def _read_text(path: Path) -> str:
    try:
        payload = path.read_bytes()
    except Exception:
        return ""
    if b"\x00" in payload[:4096]:
        return ""
    for encoding in ("utf-8", "latin-1"):
        try:
            return payload.decode(encoding)
        except Exception:
            continue
    return ""


def collect_signatures(
    repo_root: Path,
    *,
    include_extensions: set[str] | None = None,
    allowed_prefixes: Sequence[str] | None = None,
    excluded_dirs: set[str] | None = None,
    exclude_patterns: Sequence[re.Pattern[str]] | None = None,
    max_file_size_bytes: int = 1_500_000,
) -> dict[str, FileSignature]:
    include_ext = include_extensions or set(DEFAULT_INCLUDE_EXTENSIONS)
    allowed = tuple(allowed_prefixes or DEFAULT_ALLOWED_PREFIXES)
    excluded = set(excluded_dirs or DEFAULT_EXCLUDED_DIRS)
    patterns = tuple(exclude_patterns or DEFAULT_EXCLUDE_PATTERNS)

    out: dict[str, FileSignature] = {}
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        rel = str(path.relative_to(repo_root)).replace("\\", "/")
        if _is_excluded(
            rel,
            allowed_prefixes=allowed,
            excluded_dirs=excluded,
            exclude_patterns=patterns,
        ):
            continue
        if path.suffix.lower() not in include_ext and rel not in {"wsgi.py", "pyproject.toml", "requirements.txt"}:
            continue
        try:
            if int(path.stat().st_size) > int(max_file_size_bytes):
                continue
        except Exception:
            continue

        raw_text = _read_text(path)
        if not raw_text:
            continue
        lines = normalize_lines(raw_text, path.suffix.lower())
        normalized_text = "\n".join(lines)
        raw_hash = hashlib.sha256(raw_text.encode("utf-8", errors="ignore")).hexdigest()
        normalized_hash = hashlib.sha256(normalized_text.encode("utf-8", errors="ignore")).hexdigest()
        out[rel] = FileSignature(
            relative_path=rel,
            normalized_text=normalized_text,
            normalized_lines=tuple(lines),
            raw_hash=raw_hash,
            normalized_hash=normalized_hash,
        )
    return out


def _pct(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return round((num / den) * 100.0, 2)


def compare_repositories(
    source_repo: Path,
    target_repo: Path,
    *,
    max_file_size_bytes: int = 1_500_000,
) -> dict:
    source = collect_signatures(source_repo, max_file_size_bytes=max_file_size_bytes)
    target = collect_signatures(target_repo, max_file_size_bytes=max_file_size_bytes)

    source_hashes = {v.raw_hash for v in source.values() if v.raw_hash}
    target_hashes = {v.raw_hash for v in target.values() if v.raw_hash}
    source_norm_hashes = {v.normalized_hash for v in source.values() if v.normalized_hash}
    target_norm_hashes = {v.normalized_hash for v in target.values() if v.normalized_hash}

    exact_source = sum(1 for v in source.values() if v.raw_hash in target_hashes)
    exact_target = sum(1 for v in target.values() if v.raw_hash in source_hashes)
    normalized_exact_source = sum(1 for v in source.values() if v.normalized_hash in target_norm_hashes)
    normalized_exact_target = sum(1 for v in target.values() if v.normalized_hash in source_norm_hashes)

    common_paths = sorted(set(source).intersection(target))
    ratios: list[float] = []
    same_path_exact = 0
    same_path_ge90 = 0
    same_path_ge80 = 0
    top_near_examples: list[tuple[str, float]] = []
    for rel in common_paths:
        left = source[rel]
        right = target[rel]
        if left.raw_hash == right.raw_hash:
            ratio = 1.0
            same_path_exact += 1
        else:
            ratio = SequenceMatcher(None, left.normalized_text, right.normalized_text).ratio()
        ratios.append(ratio)
        if ratio >= 0.90:
            same_path_ge90 += 1
        if ratio >= 0.80:
            same_path_ge80 += 1
        if ratio < 1.0 and ratio >= 0.90:
            top_near_examples.append((rel, round(ratio * 100.0, 2)))

    source_lines = {line for v in source.values() for line in v.normalized_lines}
    target_lines = {line for v in target.values() for line in v.normalized_lines}
    line_intersection = source_lines.intersection(target_lines)

    report = {
        "counts": {
            "files_source": len(source),
            "files_target": len(target),
            "common_relative_paths": len(common_paths),
        },
        "percentages": {
            "exact_match_anywhere_pct_of_source": _pct(exact_source, len(source)),
            "exact_match_anywhere_pct_of_target": _pct(exact_target, len(target)),
            "normalized_exact_anywhere_pct_of_source": _pct(normalized_exact_source, len(source)),
            "normalized_exact_anywhere_pct_of_target": _pct(normalized_exact_target, len(target)),
            "same_path_exact_pct": _pct(same_path_exact, len(common_paths)),
            "same_path_similarity_ge_90_pct": _pct(same_path_ge90, len(common_paths)),
            "same_path_similarity_ge_80_pct": _pct(same_path_ge80, len(common_paths)),
            "same_path_average_similarity_pct": round(
                ((sum(ratios) / len(ratios)) * 100.0) if ratios else 0.0,
                2,
            ),
            "normalized_line_overlap_pct_of_source": _pct(len(line_intersection), len(source_lines)),
            "normalized_line_overlap_pct_of_target": _pct(len(line_intersection), len(target_lines)),
        },
        "raw_counts": {
            "exact_source": exact_source,
            "exact_target": exact_target,
            "normalized_exact_source": normalized_exact_source,
            "normalized_exact_target": normalized_exact_target,
            "same_path_exact": same_path_exact,
            "same_path_ge90": same_path_ge90,
            "same_path_ge80": same_path_ge80,
            "normalized_unique_lines_source": len(source_lines),
            "normalized_unique_lines_target": len(target_lines),
            "normalized_unique_lines_intersection": len(line_intersection),
        },
        "top_near_examples": sorted(top_near_examples, key=lambda item: (-item[1], item[0]))[:25],
    }
    return report


def evaluate_thresholds(
    report: Mapping[str, object],
    *,
    exact_max_pct: float | None = None,
    normalized_exact_max_pct: float | None = None,
    line_overlap_max_pct: float | None = None,
) -> list[str]:
    pct = dict(report.get("percentages") or {})
    failures: list[str] = []

    exact_source = float(pct.get("exact_match_anywhere_pct_of_source") or 0.0)
    normalized_exact_source = float(pct.get("normalized_exact_anywhere_pct_of_source") or 0.0)
    line_overlap_source = float(pct.get("normalized_line_overlap_pct_of_source") or 0.0)

    if exact_max_pct is not None and exact_source > float(exact_max_pct):
        failures.append(
            f"exact_match_anywhere_pct_of_source {exact_source:.2f}% exceeds max {float(exact_max_pct):.2f}%"
        )
    if normalized_exact_max_pct is not None and normalized_exact_source > float(normalized_exact_max_pct):
        failures.append(
            f"normalized_exact_anywhere_pct_of_source {normalized_exact_source:.2f}% exceeds max "
            f"{float(normalized_exact_max_pct):.2f}%"
        )
    if line_overlap_max_pct is not None and line_overlap_source > float(line_overlap_max_pct):
        failures.append(
            f"normalized_line_overlap_pct_of_source {line_overlap_source:.2f}% exceeds max "
            f"{float(line_overlap_max_pct):.2f}%"
        )
    return failures


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare backend repository similarity and enforce thresholds.")
    parser.add_argument("--source-repo", default=".", help="Source repository root. Defaults to current working dir.")
    parser.add_argument("--target-repo", required=True, help="Target repository root to compare against.")
    parser.add_argument("--max-file-size-bytes", type=int, default=1_500_000)
    parser.add_argument("--exact-max-pct", type=float, default=None)
    parser.add_argument("--normalized-exact-max-pct", type=float, default=None)
    parser.add_argument("--line-overlap-max-pct", type=float, default=12.0)
    parser.add_argument("--output-json", default=None, help="Optional path to write JSON report.")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    source = Path(args.source_repo).resolve()
    target = Path(args.target_repo).resolve()
    if not source.exists():
        print(f"Source repo path not found: {source}", file=sys.stderr)
        return 2
    if not target.exists():
        print(f"Target repo path not found: {target}", file=sys.stderr)
        return 2

    report = compare_repositories(source, target, max_file_size_bytes=int(args.max_file_size_bytes))
    failures = evaluate_thresholds(
        report,
        exact_max_pct=args.exact_max_pct,
        normalized_exact_max_pct=args.normalized_exact_max_pct,
        line_overlap_max_pct=args.line_overlap_max_pct,
    )
    payload = {
        "source_repo": str(source),
        "target_repo": str(target),
        "report": report,
        "threshold_failures": failures,
    }
    rendered = json.dumps(payload, indent=2)
    print(rendered)
    if args.output_json:
        out = Path(args.output_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered + "\n", encoding="utf-8")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
