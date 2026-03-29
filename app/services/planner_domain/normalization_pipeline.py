"""Ordered normalization pipeline for planner-domain plan JSON.

Owns: executing an ordered list of normalizer callables over a plan dict,
threading the plan through them, aggregating issues, and collecting debug
metadata keyed by normalizer name.

Both the initial plan pass and the retry pass in PlannerDomainService.plan()
call the same pipeline instance, ensuring the two paths never diverge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple


@dataclass
class NormalizationPipelineResult:
    """Aggregated output from a full normalization pipeline run."""

    plan: Dict[str, Any]
    all_issues: List[str]
    debug: Dict[str, Any] = field(default_factory=dict)


class NormalizationPipeline:
    """Runs an ordered sequence of normalizer callables over a plan dict.

    Each normalizer must have the signature::

        def normalizer(
            *,
            plan_json: dict,
            capabilities: Mapping[str, Any],
            prompt: str = "",
            semester_indicator_columns: Optional[dict] = None,
            domain_time_policy: Optional[dict] = None,
            today: Optional[date] = None,
            **_extra,
        ) -> tuple[dict, list[str], dict]:
            ...

    The ``**_extra`` absorbs any additional keyword arguments the pipeline may
    pass in the future without requiring signature changes.
    """

    def __init__(
        self,
        normalizers: List[Tuple[str, Callable[..., Tuple[dict, List[str], Dict[str, Any]]]]],
    ) -> None:
        self._normalizers = normalizers

    def run(
        self,
        *,
        plan: Dict[str, Any],
        capabilities: Mapping[str, Any],
        prompt: str = "",
        semester_indicator_columns: Optional[Dict[str, str]] = None,
        domain_time_policy: Optional[Mapping[str, Any]] = None,
        today: Optional[date] = None,
    ) -> NormalizationPipelineResult:
        """Execute all normalizers in order and return aggregated results.

        The output plan of each normalizer becomes the input for the next.
        Issues are concatenated in normalizer order.  Debug entries are keyed
        by normalizer name and only included when the normalizer returns a
        non-empty debug dict.
        """
        current: Dict[str, Any] = dict(plan)
        all_issues: List[str] = []
        debug: Dict[str, Any] = {}

        for name, fn in self._normalizers:
            current, issues, step_debug = fn(
                plan_json=current,
                capabilities=capabilities,
                prompt=prompt,
                semester_indicator_columns=semester_indicator_columns,
                domain_time_policy=domain_time_policy,
                today=today,
            )
            all_issues.extend(issues)
            if step_debug:
                debug[name] = step_debug

        return NormalizationPipelineResult(
            plan=current,
            all_issues=all_issues,
            debug=debug,
        )
