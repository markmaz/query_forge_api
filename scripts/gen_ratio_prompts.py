#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path
from typing import Iterable, List, Set


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _title_case_variants(text: str) -> List[str]:
    base = _normalize_space(text)
    if base == "":
        return []
    return [base, base.capitalize()]


def _ratio_metric_phrases() -> List[str]:
    return [
        "students per teacher",
        "student teacher ratio",
        "student-teacher ratio",
        "average students per teacher",
        "avg students per teacher",
        "number of students per teacher",
        "pupil teacher ratio",
        "teacher to student ratio",
        "students to teacher ratio",
        "teacher-student ratio",
    ]


def _dimensions() -> List[str]:
    return [
        "",
        "by county",
        "by school",
        "by district",
        "by grade band",
        "by campus",
        "for each county",
        "for each school",
        "for each district",
        "by county and grade band",
    ]


def _time_phrases() -> List[str]:
    return [
        "",
        "this year",
        "for this year",
        "in the current school year",
        "for the current school year",
        "last year",
        "for last year",
    ]


def _query_prefixes() -> List[str]:
    return [
        "show",
        "what is",
        "give me",
        "calculate",
        "report",
        "find",
    ]


def _distractor_templates() -> List[str]:
    # Intentionally includes "per" tokens that should not be interpreted as TIME_RANGE.
    return [
        "show attendance incidents per student by county",
        "list discipline referrals per school by district",
        "report credits earned per course by campus",
        "show average minutes per class period by school",
        "find counselor meetings per student by grade band",
        "show books checked out per library by campus",
        "list absences per weekday by district",
        "report cafeteria meals per student by school",
        "show tutoring sessions per student by county",
        "find help-desk tickets per campus by district",
        "show pass/fail records per grading period by school",
        "list interventions per student by grade band",
        "report incidents per month by campus",
        "show transport riders per route by district",
        "find parent contacts per advisor by school",
        "list logins per student by county",
        "show immunization records per nurse by campus",
        "report forms completed per semester by district",
        "show athletics entries per team by school",
        "list class enrollments per section by campus",
    ]


def _candidate_prompts() -> List[str]:
    candidates: Set[str] = set()
    for prefix in _query_prefixes():
        for metric in _ratio_metric_phrases():
            for dimension in _dimensions():
                for time_phrase in _time_phrases():
                    parts = [prefix, metric]
                    if dimension:
                        parts.append(dimension)
                    if time_phrase:
                        parts.append(time_phrase)
                    phrase = _normalize_space(" ".join(parts))
                    if phrase == "":
                        continue
                    if prefix in {"show", "report", "find"} and not phrase.endswith("?"):
                        candidates.add(phrase)
                    for variant in _title_case_variants(phrase):
                        if variant:
                            candidates.add(variant if variant.endswith("?") else f"{variant}?")
                            candidates.add(variant)
    for prompt in _distractor_templates():
        for variant in _title_case_variants(prompt):
            candidates.add(variant)
            candidates.add(f"{variant}?")
    return sorted(candidates)


def _build_records(prompts: Iterable[str]) -> List[dict]:
    out: List[dict] = []
    for prompt in prompts:
        text = _normalize_space(prompt)
        if text == "":
            continue
        out.append(
            {
                "text": text,
                "meta": {
                    "source": "gen_ratio_prompts",
                    "kind": "ratio_metric",
                },
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate targeted unlabeled ratio prompts for NER improvement.")
    parser.add_argument("--out", default="data/ratio_unlabeled.jsonl", help="Output JSONL path")
    parser.add_argument("--count", type=int, default=200, help="Number of unique prompts to write")
    parser.add_argument("--seed", type=int, default=13, help="Random seed for stable sampling")
    args = parser.parse_args()

    if args.count <= 0:
        raise ValueError("--count must be > 0")

    candidates = _candidate_prompts()
    if len(candidates) < args.count:
        raise ValueError(f"Not enough unique prompts ({len(candidates)}) to satisfy count={args.count}")

    rng = random.Random(args.seed)
    sample = list(candidates)
    rng.shuffle(sample)
    selected = sorted(sample[: args.count])
    records = _build_records(selected)

    dst = Path(args.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Wrote {len(records)} prompts to {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
