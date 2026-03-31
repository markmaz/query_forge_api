#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
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
    normalized_line_numbers: tuple[int, ...] = ()


def line_ngrams(lines: Sequence[str], n: int) -> set[tuple[str, ...]]:
    """Return the set of all n-length consecutive line tuples from *lines*."""
    result: set[tuple[str, ...]] = set()
    lines_seq = tuple(lines)
    for i in range(len(lines_seq) - n + 1):
        result.add(lines_seq[i : i + n])
    return result


def _specific_lines(signatures: dict[str, FileSignature], max_file_freq: int) -> set[str]:
    """Return lines that appear in at most *max_file_freq* distinct files."""
    freq: Counter[str] = Counter()
    for sig in signatures.values():
        for line in set(sig.normalized_lines):
            freq[line] += 1
    return {line for line, count in freq.items() if count <= max_file_freq}


def normalize_lines_numbered(text: str, extension: str) -> list[tuple[str, int]]:
    """Return (normalized_line, original_1indexed_lineno) pairs, skipping blanks/comments."""
    result: list[tuple[str, int]] = []
    content = text.replace("\r\n", "\n").replace("\r", "\n")
    for lineno, line in enumerate(content.split("\n"), start=1):
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
            result.append((token, lineno))
    return result


def normalize_lines(text: str, extension: str) -> list[str]:
    return [line for line, _ in normalize_lines_numbered(text, extension)]


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
        numbered = normalize_lines_numbered(raw_text, path.suffix.lower())
        lines = [line for line, _ in numbered]
        line_numbers = [lineno for _, lineno in numbered]
        normalized_text = "\n".join(lines)
        raw_hash = hashlib.sha256(raw_text.encode("utf-8", errors="ignore")).hexdigest()
        normalized_hash = hashlib.sha256(normalized_text.encode("utf-8", errors="ignore")).hexdigest()
        out[rel] = FileSignature(
            relative_path=rel,
            normalized_text=normalized_text,
            normalized_lines=tuple(lines),
            raw_hash=raw_hash,
            normalized_hash=normalized_hash,
            normalized_line_numbers=tuple(line_numbers),
        )
    return out


def find_clone_locations(
    intersection_ngrams: set[tuple[str, ...]],
    source_sigs: dict[str, FileSignature],
    target_sigs: dict[str, FileSignature],
    max_clones: int = 20,
) -> list[dict]:
    """Map each intersecting n-gram back to exact file paths and line numbers.

    Returns a list of dicts, each with:
      - ``lines``: the shared n-gram as a list of normalized strings
      - ``source_locations``: list of {"file", "start_line", "end_line"}
      - ``target_locations``: list of {"file", "start_line", "end_line"}
    """

    def _locate(ngram: tuple[str, ...], sigs: dict[str, FileSignature]) -> list[dict]:
        locations: list[dict] = []
        n = len(ngram)
        for sig in sigs.values():
            nl = sig.normalized_lines
            nums = sig.normalized_line_numbers
            if len(nl) < n or not nums:
                continue
            for i in range(len(nl) - n + 1):
                if nl[i : i + n] == ngram:
                    locations.append({
                        "file": sig.relative_path,
                        "start_line": nums[i],
                        "end_line": nums[i + n - 1],
                    })
        return locations

    results: list[dict] = []
    for ngram in intersection_ngrams:
        src_locs = _locate(ngram, source_sigs)
        tgt_locs = _locate(ngram, target_sigs)
        if src_locs and tgt_locs:
            results.append({
                "lines": list(ngram),
                "source_locations": src_locs,
                "target_locations": tgt_locs,
            })
        if len(results) >= max_clones:
            break
    return results


def _pct(num: int, den: int) -> float:
    if den <= 0:
        return 0.0
    return round((num / den) * 100.0, 2)


def compare_repositories(
    source_repo: Path,
    target_repo: Path,
    *,
    max_file_size_bytes: int = 1_500_000,
    max_file_freq: int = 3,
    ngram_size: int = 3,
    max_clones: int = 20,
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

    # Frequency-filtered lines: exclude boilerplate that appears in too many files
    specific_src = _specific_lines(source, max_file_freq)
    specific_tgt = _specific_lines(target, max_file_freq)
    specific_intersection = specific_src.intersection(specific_tgt)

    # N-grams built from frequency-filtered lines only
    def _repo_specific_ngrams(sigs: dict, specific: set[str]) -> set[tuple[str, ...]]:
        result: set[tuple[str, ...]] = set()
        for sig in sigs.values():
            filtered = tuple(line for line in sig.normalized_lines if line in specific)
            result.update(line_ngrams(filtered, ngram_size))
        return result

    specific_ngrams_src = _repo_specific_ngrams(source, specific_src)
    specific_ngrams_tgt = _repo_specific_ngrams(target, specific_tgt)
    specific_ngrams_intersection = specific_ngrams_src.intersection(specific_ngrams_tgt)

    clone_instances = find_clone_locations(
        specific_ngrams_intersection,
        source,
        target,
        max_clones=max_clones,
    )

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
            "specific_line_overlap_pct_of_source": _pct(len(specific_intersection), len(specific_src)),
            "specific_line_overlap_pct_of_target": _pct(len(specific_intersection), len(specific_tgt)),
            "specific_ngram_overlap_pct_of_source": _pct(len(specific_ngrams_intersection), len(specific_ngrams_src)),
            "specific_ngram_overlap_pct_of_target": _pct(len(specific_ngrams_intersection), len(specific_ngrams_tgt)),
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
            "specific_unique_lines_source": len(specific_src),
            "specific_unique_lines_target": len(specific_tgt),
            "specific_unique_lines_intersection": len(specific_intersection),
            "specific_unique_ngrams_source": len(specific_ngrams_src),
            "specific_unique_ngrams_target": len(specific_ngrams_tgt),
            "specific_unique_ngrams_intersection": len(specific_ngrams_intersection),
        },
        "top_near_examples": sorted(top_near_examples, key=lambda item: (-item[1], item[0]))[:25],
        "clone_instances": clone_instances,
    }
    return report


def evaluate_thresholds(
    report: Mapping[str, object],
    *,
    exact_max_pct: float | None = None,
    normalized_exact_max_pct: float | None = None,
    line_overlap_max_pct: float | None = None,
    specific_ngram_overlap_max_pct: float | None = None,
) -> list[str]:
    pct = dict(report.get("percentages") or {})
    failures: list[str] = []

    exact_source = float(pct.get("exact_match_anywhere_pct_of_source") or 0.0)
    normalized_exact_source = float(pct.get("normalized_exact_anywhere_pct_of_source") or 0.0)
    line_overlap_source = float(pct.get("normalized_line_overlap_pct_of_source") or 0.0)
    specific_ngram_source = float(pct.get("specific_ngram_overlap_pct_of_source") or 0.0)

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
    if specific_ngram_overlap_max_pct is not None and specific_ngram_source > float(specific_ngram_overlap_max_pct):
        failures.append(
            f"specific_ngram_overlap_pct_of_source {specific_ngram_source:.2f}% exceeds max "
            f"{float(specific_ngram_overlap_max_pct):.2f}%"
        )
    return failures


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare backend repository similarity and enforce thresholds.")
    parser.add_argument("--source-repo", default=".", help="Source repository root. Defaults to current working dir.")
    parser.add_argument("--target-repo", required=True, help="Target repository root to compare against.")
    parser.add_argument("--max-file-size-bytes", type=int, default=1_500_000)
    parser.add_argument("--max-file-freq", type=int, default=3,
                        help="Max files a line may appear in before being treated as boilerplate (default: 3).")
    parser.add_argument("--ngram-size", type=int, default=3,
                        help="Consecutive-line window size for logic-block comparison (default: 3).")
    parser.add_argument("--exact-max-pct", type=float, default=None)
    parser.add_argument("--normalized-exact-max-pct", type=float, default=None)
    parser.add_argument("--line-overlap-max-pct", type=float, default=12.0)
    parser.add_argument("--specific-ngram-overlap-max-pct", type=float, default=None,
                        help="Gate on frequency-filtered n-gram overlap (% of source). Recommended for logic similarity.")
    parser.add_argument("--max-clones", type=int, default=20,
                        help="Maximum number of clone instances to report (default: 20).")
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

    report = compare_repositories(
        source,
        target,
        max_file_size_bytes=int(args.max_file_size_bytes),
        max_file_freq=int(args.max_file_freq),
        ngram_size=int(args.ngram_size),
        max_clones=int(args.max_clones),
    )
    failures = evaluate_thresholds(
        report,
        exact_max_pct=args.exact_max_pct,
        normalized_exact_max_pct=args.normalized_exact_max_pct,
        line_overlap_max_pct=args.line_overlap_max_pct,
        specific_ngram_overlap_max_pct=args.specific_ngram_overlap_max_pct,
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
