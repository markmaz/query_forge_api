"""Shared frozen dataclasses for the query_forge package.

Extracted from query_forge_service.py so they can be imported by the new
sub-modules without circular dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class CompilationContext:
    """Immutable bundle of the five rewrite/derivation maps used during compilation.

    Previously these five dicts were threaded as individual parameters through
    every compile helper.  Grouping them into a single frozen dataclass makes
    call-sites cleaner and prevents accidental mutation mid-compilation.
    """

    derived_by_exprid: Dict[str, Any]
    derived_by_name: Dict[str, Any]
    rewrite_by_colname: Dict[str, Any]
    rewrite_by_modelid: Dict[Any, Any]
    rewrite_by_wt_col: Dict[Any, Any]


@dataclass(frozen=True)
class ForgeCompiledQuery:
    sql: str
    qf_count_sql: str
    params: Dict[str, Any]
    qf_output_cols: List[Dict[str, Any]]


@dataclass(frozen=True)
class QueryForgeRunResult:
    sql: str
    qf_rendered_sql: str
    params: Dict[str, Any]
    rows: List[Any]
    columns: List[Dict[str, Any]]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True)
class QueryForgePreparedQuery:
    sql: str
    qf_rendered_sql: str
    params: Dict[str, Any]
    qf_count_sql: str
    columns: List[Dict[str, Any]]
    limit: int
    offset: int
