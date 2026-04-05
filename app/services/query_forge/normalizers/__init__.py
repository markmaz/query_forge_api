"""Normalization pipeline for query_forge query JSON.

Owns: executing an ordered list of normalizer callables over a query dict,
threading the query through them, aggregating issues, and collecting debug
metadata keyed by normalizer name.

Each normalizer must have the signature::

    def normalizer(
        *,
        query_json: dict,
        domain_columns: dict,
        **_extra,
    ) -> tuple[dict, list[str], dict]:
        ...

The ``**_extra`` absorbs any additional keyword arguments the pipeline may
pass in the future without requiring signature changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Tuple

from app.services.query_forge.normalizers.query_json import QueryForgeQueryNormalizer


@dataclass
class NormalizationPipelineResult:
    """Aggregated output from a full normalization pipeline run."""

    query_json: Dict[str, Any]
    all_issues: List[str]
    debug: Dict[str, Any] = field(default_factory=dict)


class NormalizationPipeline:
    """Runs an ordered sequence of normalizer callables over a query dict."""

    def __init__(
        self,
        normalizers: List[Tuple[str, Callable[..., Tuple[dict, List[str], Dict[str, Any]]]]],
    ) -> None:
        self._normalizers = normalizers

    def run(
        self,
        *,
        query_json: Dict[str, Any],
        domain_columns: Mapping[str, Any],
    ) -> NormalizationPipelineResult:
        """Execute all normalizers in order and return aggregated results."""
        current: Dict[str, Any] = dict(query_json)
        all_issues: List[str] = []
        debug: Dict[str, Any] = {}

        for name, fn in self._normalizers:
            current, issues, step_debug = fn(
                query_json=current,
                domain_columns=domain_columns,
            )
            all_issues.extend(issues)
            if step_debug:
                debug[name] = step_debug

        return NormalizationPipelineResult(
            query_json=current,
            all_issues=all_issues,
            debug=debug,
        )


__all__ = [
    "NormalizationPipeline",
    "NormalizationPipelineResult",
    "QueryForgeQueryNormalizer",
]
