from __future__ import annotations

import json
from pathlib import Path

from scripts import similarity_gate


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_compare_repositories_counts_exact_and_normalized(tmp_path: Path) -> None:
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    _write(src / "app/services/a.py", "def f():\n    return 1\n")
    _write(tgt / "app/services/a.py", "def f():\n    return 1\n")

    # raw differs due to comment, normalized should match
    _write(src / "app/services/b.py", "def g():\n    # source comment\n    return 2\n")
    _write(tgt / "app/services/b.py", "def g():\n    # target comment\n    return 2\n")

    report = similarity_gate.compare_repositories(src, tgt)
    pct = report["percentages"]
    assert report["counts"]["files_source"] == 2
    assert pct["exact_match_anywhere_pct_of_source"] == 50.0
    assert pct["normalized_exact_anywhere_pct_of_source"] == 100.0


def test_collect_signatures_excludes_noise_dirs(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _write(root / "app/services/ok.py", "print('ok')\n")
    _write(root / ".venv/lib/skip.py", "print('skip')\n")
    _write(root / "data/skip.py", "print('skip')\n")
    _write(root / "models/skip.py", "print('skip')\n")

    sig = similarity_gate.collect_signatures(root)
    assert "app/services/ok.py" in sig
    assert ".venv/lib/skip.py" not in sig
    assert "data/skip.py" not in sig
    assert "models/skip.py" not in sig


def test_threshold_evaluation_flags_failures(tmp_path: Path) -> None:
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    _write(src / "app/services/a.py", "def f():\n    return 1\n")
    _write(tgt / "app/services/a.py", "def f():\n    return 1\n")
    report = similarity_gate.compare_repositories(src, tgt)

    failures = similarity_gate.evaluate_thresholds(
        report,
        exact_max_pct=10.0,
        normalized_exact_max_pct=10.0,
        line_overlap_max_pct=10.0,
    )
    assert failures
    assert any("exact_match_anywhere_pct_of_source" in msg for msg in failures)


# ---------------------------------------------------------------------------
# normalize_lines_numbered — returns (line, original_1indexed_lineno) pairs
# ---------------------------------------------------------------------------


def test_normalize_lines_numbered_returns_correct_line_numbers() -> None:
    text = "def f():\n    # comment\n    return 1\n"
    result = similarity_gate.normalize_lines_numbered(text, ".py")
    # comment stripped; "def f():" is line 1, "return 1" is line 3
    assert result == [("def f():", 1), ("return 1", 3)]


def test_normalize_lines_numbered_blank_lines_not_counted() -> None:
    text = "a = 1\n\n\nb = 2\n"
    result = similarity_gate.normalize_lines_numbered(text, ".py")
    assert result == [("a = 1", 1), ("b = 2", 4)]


def test_normalize_lines_numbered_empty_file_returns_empty() -> None:
    assert similarity_gate.normalize_lines_numbered("", ".py") == []


# ---------------------------------------------------------------------------
# FileSignature.normalized_line_numbers — tracks original positions
# ---------------------------------------------------------------------------


def test_file_signature_has_normalized_line_numbers_field() -> None:
    sig = similarity_gate.FileSignature(
        relative_path="a.py",
        normalized_text="",
        normalized_lines=("return 1",),
        normalized_line_numbers=(3,),
        raw_hash=None,
        normalized_hash=None,
    )
    assert sig.normalized_line_numbers == (3,)


def test_collect_signatures_populates_line_numbers(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    # line 1: def f():, line 2: comment (stripped), line 3: return 1
    _write(root / "app/services/a.py", "def f():\n    # skip\n    return 1\n")
    sigs = similarity_gate.collect_signatures(root)
    sig = sigs["app/services/a.py"]
    assert len(sig.normalized_line_numbers) == len(sig.normalized_lines)
    assert 1 in sig.normalized_line_numbers  # "def f():" was on line 1
    assert 3 in sig.normalized_line_numbers  # "return 1" was on line 3


# ---------------------------------------------------------------------------
# find_clone_locations — maps n-gram back to file:line
# ---------------------------------------------------------------------------


def test_find_clone_locations_returns_source_and_target_locations(tmp_path: Path) -> None:
    block = "x = validate(value)\nif not x:\n    raise valueerror('bad')\n"
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    _write(src / "app/services/a.py", block)
    _write(tgt / "app/services/a.py", block)
    src_sigs = similarity_gate.collect_signatures(src)
    tgt_sigs = similarity_gate.collect_signatures(tgt)

    # build intersection n-grams manually
    specific_src = similarity_gate._specific_lines(src_sigs, max_file_freq=3)
    specific_tgt = similarity_gate._specific_lines(tgt_sigs, max_file_freq=3)

    def _repo_ngrams(sigs, specific):
        result = set()
        for sig in sigs.values():
            filtered = tuple(line for line in sig.normalized_lines if line in specific)
            result.update(similarity_gate.line_ngrams(filtered, 3))
        return result

    src_ngrams = _repo_ngrams(src_sigs, specific_src)
    tgt_ngrams = _repo_ngrams(tgt_sigs, specific_tgt)
    intersection = src_ngrams.intersection(tgt_ngrams)

    clones = similarity_gate.find_clone_locations(
        intersection_ngrams=intersection,
        source_sigs=src_sigs,
        target_sigs=tgt_sigs,
    )
    assert len(clones) > 0
    clone = clones[0]
    assert "lines" in clone
    assert "source_locations" in clone
    assert "target_locations" in clone
    assert clone["source_locations"][0]["file"] == "app/services/a.py"
    assert "start_line" in clone["source_locations"][0]
    assert "end_line" in clone["source_locations"][0]


def test_find_clone_locations_line_numbers_are_one_indexed(tmp_path: Path) -> None:
    # block starts on line 1 of the file
    block = "result = compute(x)\nif result is none:\n    return default\n"
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    _write(src / "app/services/a.py", block)
    _write(tgt / "app/services/a.py", block)
    src_sigs = similarity_gate.collect_signatures(src)
    tgt_sigs = similarity_gate.collect_signatures(tgt)
    specific_src = similarity_gate._specific_lines(src_sigs, max_file_freq=3)
    specific_tgt = similarity_gate._specific_lines(tgt_sigs, max_file_freq=3)

    def _repo_ngrams(sigs, specific):
        result = set()
        for sig in sigs.values():
            filtered = tuple(line for line in sig.normalized_lines if line in specific)
            result.update(similarity_gate.line_ngrams(filtered, 3))
        return result

    intersection = _repo_ngrams(src_sigs, specific_src).intersection(
        _repo_ngrams(tgt_sigs, specific_tgt)
    )
    clones = similarity_gate.find_clone_locations(
        intersection_ngrams=intersection,
        source_sigs=src_sigs,
        target_sigs=tgt_sigs,
    )
    loc = clones[0]["source_locations"][0]
    assert loc["start_line"] >= 1
    assert loc["end_line"] >= loc["start_line"]


def test_find_clone_locations_respects_max_clones(tmp_path: Path) -> None:
    # create many unique 3-line blocks that are shared
    lines = []
    for i in range(20):
        lines += [f"unique_func_{i}()", f"value_{i} = result_{i}", f"store_{i}(value_{i})"]
    content = "\n".join(lines) + "\n"
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    _write(src / "app/services/a.py", content)
    _write(tgt / "app/services/a.py", content)
    src_sigs = similarity_gate.collect_signatures(src)
    tgt_sigs = similarity_gate.collect_signatures(tgt)
    specific_src = similarity_gate._specific_lines(src_sigs, max_file_freq=3)
    specific_tgt = similarity_gate._specific_lines(tgt_sigs, max_file_freq=3)

    def _repo_ngrams(sigs, specific):
        result = set()
        for sig in sigs.values():
            filtered = tuple(line for line in sig.normalized_lines if line in specific)
            result.update(similarity_gate.line_ngrams(filtered, 3))
        return result

    intersection = _repo_ngrams(src_sigs, specific_src).intersection(
        _repo_ngrams(tgt_sigs, specific_tgt)
    )
    clones = similarity_gate.find_clone_locations(
        intersection_ngrams=intersection,
        source_sigs=src_sigs,
        target_sigs=tgt_sigs,
        max_clones=5,
    )
    assert len(clones) <= 5


# ---------------------------------------------------------------------------
# compare_repositories — clone_instances in report
# ---------------------------------------------------------------------------


def test_compare_repositories_includes_clone_instances_key(tmp_path: Path) -> None:
    block = "a = process(x)\nif a is none:\n    return fallback\n"
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    _write(src / "app/services/a.py", block)
    _write(tgt / "app/services/a.py", block)
    report = similarity_gate.compare_repositories(src, tgt)
    assert "clone_instances" in report


def test_compare_repositories_clone_instances_populated_when_overlap(tmp_path: Path) -> None:
    block = "a = process(x)\nif a is none:\n    return fallback\n"
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    _write(src / "app/services/a.py", block)
    _write(tgt / "app/services/a.py", block)
    report = similarity_gate.compare_repositories(src, tgt)
    assert len(report["clone_instances"]) > 0


def test_compare_repositories_clone_instances_empty_when_no_overlap(tmp_path: Path) -> None:
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    _write(src / "app/services/a.py", "def f():\n    return 1\n")
    _write(tgt / "app/services/b.py", "def g():\n    return 999\n")
    report = similarity_gate.compare_repositories(src, tgt)
    assert report["clone_instances"] == []


# ---------------------------------------------------------------------------
# CLI — max-clones argument
# ---------------------------------------------------------------------------


def test_cli_accepts_max_clones_arg(tmp_path: Path) -> None:
    block = "x = compute(v)\nif x is none:\n    raise valueerror('missing')\n"
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    out_json = tmp_path / "report.json"
    _write(src / "app/services/a.py", block)
    _write(tgt / "app/services/a.py", block)
    similarity_gate.main([
        "--source-repo", str(src),
        "--target-repo", str(tgt),
        "--max-clones", "10",
        "--output-json", str(out_json),
    ])
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert "clone_instances" in payload["report"]


# ---------------------------------------------------------------------------
# line_ngrams — pure function
# ---------------------------------------------------------------------------


def test_line_ngrams_empty_input_returns_empty_set() -> None:
    assert similarity_gate.line_ngrams((), 3) == set()


def test_line_ngrams_input_shorter_than_n_returns_empty_set() -> None:
    assert similarity_gate.line_ngrams(("a", "b"), 3) == set()


def test_line_ngrams_exact_length_returns_one_gram() -> None:
    result = similarity_gate.line_ngrams(("a", "b", "c"), 3)
    assert result == {("a", "b", "c")}


def test_line_ngrams_four_lines_returns_two_grams() -> None:
    result = similarity_gate.line_ngrams(("a", "b", "c", "d"), 3)
    assert result == {("a", "b", "c"), ("b", "c", "d")}


def test_line_ngrams_n1_returns_each_line_as_singleton() -> None:
    result = similarity_gate.line_ngrams(("x", "y"), 1)
    assert result == {("x",), ("y",)}


# ---------------------------------------------------------------------------
# _specific_lines — frequency filter
# ---------------------------------------------------------------------------


def _make_sig(rel: str, lines: tuple[str, ...]) -> similarity_gate.FileSignature:
    text = "\n".join(lines)
    return similarity_gate.FileSignature(
        relative_path=rel,
        normalized_text=text,
        normalized_lines=lines,
        raw_hash=None,
        normalized_hash=None,
    )


def test_specific_lines_excludes_line_in_too_many_files() -> None:
    # "return none" appears in 4 files — above the default max_file_freq of 3
    sigs = {
        "a.py": _make_sig("a.py", ("return none", "unique_a")),
        "b.py": _make_sig("b.py", ("return none", "unique_b")),
        "c.py": _make_sig("c.py", ("return none", "unique_c")),
        "d.py": _make_sig("d.py", ("return none", "unique_d")),
    }
    specific = similarity_gate._specific_lines(sigs, max_file_freq=3)
    assert "return none" not in specific
    assert "unique_a" in specific


def test_specific_lines_keeps_line_at_or_under_threshold() -> None:
    sigs = {
        "a.py": _make_sig("a.py", ("shared_logic", "unique_a")),
        "b.py": _make_sig("b.py", ("shared_logic", "unique_b")),
        "c.py": _make_sig("c.py", ("shared_logic", "unique_c")),
    }
    specific = similarity_gate._specific_lines(sigs, max_file_freq=3)
    assert "shared_logic" in specific


def test_specific_lines_counts_per_file_not_total_occurrences() -> None:
    # same line repeated 10 times in ONE file still counts as freq=1
    sigs = {
        "a.py": _make_sig("a.py", ("repeated",) * 10),
    }
    specific = similarity_gate._specific_lines(sigs, max_file_freq=1)
    assert "repeated" in specific


# ---------------------------------------------------------------------------
# compare_repositories — new report keys
# ---------------------------------------------------------------------------


def test_compare_repositories_report_includes_specific_line_overlap_keys(tmp_path: Path) -> None:
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    _write(src / "app/services/a.py", "def f():\n    return 1\n")
    _write(tgt / "app/services/a.py", "def f():\n    return 1\n")
    report = similarity_gate.compare_repositories(src, tgt)
    assert "specific_line_overlap_pct_of_source" in report["percentages"]
    assert "specific_line_overlap_pct_of_target" in report["percentages"]


def test_compare_repositories_report_includes_ngram_overlap_keys(tmp_path: Path) -> None:
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    _write(src / "app/services/a.py", "def f():\n    return 1\n")
    _write(tgt / "app/services/a.py", "def f():\n    return 1\n")
    report = similarity_gate.compare_repositories(src, tgt)
    assert "specific_ngram_overlap_pct_of_source" in report["percentages"]
    assert "specific_ngram_overlap_pct_of_target" in report["percentages"]


def test_ngram_overlap_detects_shared_logic_block(tmp_path: Path) -> None:
    block = (
        "if value is none:\n"
        "    raise valueerror('missing')\n"
        "return str(value).strip()\n"
        "result = process(value)\n"
    )
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    _write(src / "app/services/a.py", block)
    _write(tgt / "app/services/a.py", block)
    report = similarity_gate.compare_repositories(src, tgt)
    assert report["percentages"]["specific_ngram_overlap_pct_of_source"] > 0


def test_ngram_overlap_zero_when_only_isolated_common_lines(tmp_path: Path) -> None:
    # Each file has common Python lines but in different sequences / contexts
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    _write(src / "app/services/a.py", "def f():\n    return None\n")
    _write(src / "app/services/b.py", "def g():\n    return None\n")
    _write(src / "app/services/c.py", "def h():\n    return None\n")
    _write(src / "app/services/d.py", "def j():\n    return None\n")
    # target has same boilerplate lines but completely different sequences
    _write(tgt / "app/services/x.py", "class Foo:\n    pass\nreturn None\n")
    _write(tgt / "app/services/y.py", "class Bar:\n    pass\nreturn None\n")
    report = similarity_gate.compare_repositories(src, tgt)
    # "return none" is high-frequency across src files — filtered out before ngrams
    # so no n-gram overlap should survive the frequency filter
    assert report["percentages"]["specific_ngram_overlap_pct_of_source"] == 0.0


# ---------------------------------------------------------------------------
# evaluate_thresholds — new threshold
# ---------------------------------------------------------------------------


def test_evaluate_thresholds_flags_specific_ngram_overlap_failure(tmp_path: Path) -> None:
    block = (
        "result = validate(x)\n"
        "if not result:\n"
        "    raise valueerror('bad')\n"
        "return result\n"
    )
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    _write(src / "app/services/a.py", block)
    _write(tgt / "app/services/a.py", block)
    report = similarity_gate.compare_repositories(src, tgt)
    failures = similarity_gate.evaluate_thresholds(report, specific_ngram_overlap_max_pct=0.0)
    assert any("specific_ngram" in msg for msg in failures)


def test_evaluate_thresholds_passes_when_specific_ngram_under_limit(tmp_path: Path) -> None:
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    _write(src / "app/services/a.py", "def f():\n    return 1\n")
    _write(tgt / "app/services/b.py", "def g():\n    return 2\n")
    report = similarity_gate.compare_repositories(src, tgt)
    failures = similarity_gate.evaluate_thresholds(report, specific_ngram_overlap_max_pct=100.0)
    assert not any("specific_ngram" in msg for msg in failures)


# ---------------------------------------------------------------------------
# CLI — new arguments
# ---------------------------------------------------------------------------


def test_cli_accepts_max_file_freq_and_ngram_size_args(tmp_path: Path) -> None:
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    out_json = tmp_path / "report.json"
    _write(src / "app/services/a.py", "def f():\n    return 1\n")
    _write(tgt / "app/services/a.py", "def f():\n    return 1\n")
    similarity_gate.main([
        "--source-repo", str(src),
        "--target-repo", str(tgt),
        "--max-file-freq", "5",
        "--ngram-size", "2",
        "--output-json", str(out_json),
    ])
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert "specific_ngram_overlap_pct_of_source" in payload["report"]["percentages"]


def test_cli_specific_ngram_threshold_causes_failure(tmp_path: Path) -> None:
    block = "def f():\n    x = 1\n    y = 2\n    return x + y\n"
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    _write(src / "app/services/a.py", block)
    _write(tgt / "app/services/a.py", block)
    code = similarity_gate.main([
        "--source-repo", str(src),
        "--target-repo", str(tgt),
        "--specific-ngram-overlap-max-pct", "0.0",
    ])
    assert code == 1


# ---------------------------------------------------------------------------
# Existing CLI test (unchanged)
# ---------------------------------------------------------------------------


def test_cli_main_writes_json_and_returns_nonzero_on_failure(tmp_path: Path) -> None:
    src = tmp_path / "src"
    tgt = tmp_path / "tgt"
    out_json = tmp_path / "report" / "sim.json"
    _write(src / "app/services/a.py", "def f():\n    return 1\n")
    _write(tgt / "app/services/a.py", "def f():\n    return 1\n")

    code = similarity_gate.main(
        [
            "--source-repo",
            str(src),
            "--target-repo",
            str(tgt),
            "--exact-max-pct",
            "0.0",
            "--output-json",
            str(out_json),
        ]
    )
    assert code == 1
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["threshold_failures"]
    assert payload["report"]["counts"]["files_source"] == 1
