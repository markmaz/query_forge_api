# QueryForge Service Refactor Spec

> **Implementation note**
> Read this file fully before refactoring `app/services/query_forge_service.py`.
> The goal is to reduce risk while shrinking the file into an orchestration layer.
> Preserve SQL output behavior unless this spec explicitly calls out a contract change.

---

## Goal

Refactor `app/services/query_forge_service.py` (3,678 lines, 56 methods in one class) into a new package `app/services/query_forge/` with a thin orchestration facade plus focused, independently testable modules.

This is **not** a rewrite. It is a staged extraction with behavior preservation.

Success means:

- `query_forge_service.py` is a one-line re-export shim — no logic remains in it.
- `QueryForgeService` in `service.py` contains only dependency wiring and phase orchestration — no helper function bodies.
- Each extracted module has its own unit tests written **before** the extraction (TDD).
- SQL output is unchanged for equivalent inputs.
- The public API is cleaner and more distinct from `no_code_query_service.py` in the workboard codebase.

---

## Why This Refactor Is Needed

`query_forge_service.py` currently mixes:

- Public query API (`run`, `prepare`, `compile`, `normalize`)
- SQL identifier escaping and rendering utilities
- Input normalization and validation
- Query compilation orchestration (521-line `compile()`)
- DataPrep CTE compilation (~380 lines across 5 methods)
- Split ratio query compilation (307-line separate path)
- WHERE clause and filter tree compilation (364 lines)
- Table dependency resolution and join planning
- Result row/column/total extraction
- Domain-specific severity filtering

Ten+ methods thread a cluster of five rewrite maps (`derived_by_exprid`, `derived_by_name`, `rewrite_by_colname`, `rewrite_by_modelid`, `rewrite_by_wt_col`) as individual parameters, causing parameter explosion across the call graph.

The file's structure closely mirrors `no_code_query_service.py` in the workboard codebase (confirmed by similarity analysis), making the two hard to evolve independently.

---

## Non-Goals

This refactor must **not**:

- Change SQL dialect or query semantics
- Alter database schema or ORM models
- Introduce new query features or change normalization rules
- Merge query_forge with the planner domain service
- Remove the `mode` parameter from the public API
- Change the executor interface or how `QueryForgeService` receives its executor

---

## Constraints

1. Every extraction is preceded by failing unit tests — no production code moves without a red test first.
2. No single phase moves more than ~800 lines.
3. New modules live under `app/services/query_forge/`.
4. `app/services/query_forge_service.py` becomes a one-line re-export shim after Phase 8 — no route import breaks.
5. No cyclic imports between new modules.
6. Extract leaf helpers first; touch the orchestration core (Phase 8) last.
7. Each phase ends with the full test suite passing.

---

## Current Responsibility Clusters

These clusters are visible in the file today:

1. **Types** — `ForgeCompiledQuery`, `QueryForgeRunResult`, `QueryForgePreparedQuery` dataclasses (lines 60–88)
2. **SQL utilities** — `_qf_safe_ident`, `_safe_alias`, `_safe_table_full_name`, `_literal_sql`, `_qf_render_sql` (lines 2670–2761)
3. **Result processing** — `_qf_cols_from_json`, `_qf_infer_cols`, `_qf_extract_total`, `_qf_rows_to_dicts` (lines 3607–3678)
4. **Normalization** — `normalize()` (lines 227–519), `_qf_norm_filters` (lines 176–226), `_qf_norm_col_key` (lines 576–607), `_qf_norm_metric_expr` (lines 608–658), and static metric helpers (lines 520–575)
5. **DataPrep compilation** — `_compile_data_prep_meta` (lines 1989–2243), `_build_prep_base_selects` (lines 2581–2669), `_qf_compile_dp_cte` (line 1954), `_render_data_prep_cte` (line 2244), `_dp_ident` (line 2732)
6. **Split ratio compilation** — `_detect_split_ratio_metric` (lines 1582–1646), `_compile_split_ratio_query` (lines 1647–1953)
7. **WHERE compilation** — `_compile_where` (lines 2969–3332), `_is_and_only_filter_tree` (line 1019), `_flatten_and_conditions` (line 1037), `_build_and_filter_tree` (line 1053)
8. **Orchestration core** — `__init__`, `run`, `prepare`, `compile`, and all remaining table-resolution/join/metric/attachment/order-by methods

**Methods that stay in `service.py`:**
- `_parse_join_expr` — called only from `_compile_join_side`, which stays in the orchestration core
- `_effective_filter_mode` — called from `_required_table_ids_from_query` and `_collect_required_column_keys` (orchestration core) as well as from `_compile_where`; stays in `service.py` and is passed as a callable or re-called at each site

---

## Target Module Layout

```
app/services/query_forge/
    __init__.py               # re-exports QueryForgeService
    service.py                # thin orchestration facade
    types.py                  # dataclasses + CompilationContext
    sql_utils.py              # stateless SQL escaping and rendering
    result_mapper.py          # row/column/total extraction from executor results
    normalizers/
        __init__.py           # NormalizationPipeline (same pattern as planner_domain)
        columns.py            # column reference + metric expression normalizers
        filters.py            # filter tree normalizer
        aggregations.py       # aggregation/sorting normalizer
        attachments.py        # value override / attachment normalizer
        derived.py            # DataPrep / derived expression normalizer
    data_prep_compiler.py     # DataPrep CTE compilation; returns CompilationContext
    split_ratio_compiler.py   # split ratio query path
    where_compiler.py         # WHERE clause compilation

app/services/query_forge_service.py   # one-line shim (after Phase 8)
```

**Shim content (after Phase 8):**
```python
from app.services.query_forge.service import QueryForgeService  # noqa: F401
```

---

## Key Design Decisions

### CompilationContext

The five rewrite maps currently threaded as individual parameters through 10+ methods become a single frozen dataclass defined in `types.py`:

```python
@dataclass(frozen=True)
class CompilationContext:
    derived_by_exprid: dict[str, Any]
    derived_by_name: dict[str, Any]
    rewrite_by_colname: dict[str, Any]
    rewrite_by_modelid: dict[str, Any]
    rewrite_by_wt_col: dict[str, Any]
```

`DataPrepCompiler` builds and returns one. The orchestration core receives it and passes it as a single argument to `_col_expr`, WHERE compilation, metric compilation, etc. — eliminating 4–5 extra parameter slots on each of those methods.

### NormalizationPipeline

Same pattern as `planner_domain/normalizers/`. Each normalizer has the signature:

```python
def normalizer(
    *,
    query_json: dict,
    domain_columns: dict,
    **_extra,
) -> tuple[dict, list[str], dict]:
    ...
```

Returns `(normalized_query, issues, debug)`. The `domain_columns` argument carries the column catalog needed for validation (equivalent to `capabilities` in the planner domain pipeline). The pipeline threads normalizers in order:

```
columns → filters → aggregations → attachments → derived
```

The pipeline instance is constructed once in `QueryForgeService.__init__`. The existing `normalize()` method becomes internal (`_normalize()`), which calls:

```python
result = self._normalization.run(
    query_json=raw_query,
    domain_columns=self._load_domain_column_catalog(),
)
```

### Public API (Phase 8)

The current signatures are:

```python
# Current (in query_api.py:109, skill_runner.py:210, query_analysis_routes.py:357)
svc.run(raw_query=raw, mode=mode, limit=limit, offset=offset)
svc.run(raw_query=sql_json, mode="export", limit=_SKILL_EXECUTE_ROW_CAP, offset=0)
svc.run(raw_query=sql_json, mode="export", limit=500, offset=0)
```

The Phase 8 cleanup renames `raw_query` → `query_json` and makes all parameters keyword-only. `mode` is retained. `compile()` and `normalize()` become internal (`_compile()`, `_normalize()`). The updated signatures are:

```python
class QueryForgeService:
    def run(
        self,
        query_json: dict,
        *,
        mode: str = "preview",
        limit: int = 200,
        offset: int = 0,
    ) -> QueryForgeRunResult: ...

    def prepare(
        self,
        query_json: dict,
        *,
        mode: str = "preview",
        limit: int = 200,
        offset: int = 0,
    ) -> QueryForgePreparedQuery: ...
```

**Route call-site migrations (Phase 8):**

| File | Before | After |
|------|--------|-------|
| `app/features/query_engine/query_api.py:109` | `svc.run(raw_query=raw, mode=mode, ...)` | `svc.run(raw, mode=mode, ...)` |
| `app/tasks/skill_runner.py:210` | `svc.run(raw_query=sql_json, mode="export", ...)` | `svc.run(sql_json, mode="export", ...)` |
| `app/routes/query_analysis_routes.py:357` | `svc.run(raw_query=sql_json, mode="export", ...)` | `svc.run(sql_json, mode="export", ...)` |

This is a minimal API change — the rename from `raw_query` to `query_json` (first positional argument) is the only observable difference at call sites. `mode` is preserved.

---

## Phase Breakdown

### Phase 1 — `types.py`

**What moves:** `ForgeCompiledQuery`, `QueryForgeRunResult`, `QueryForgePreparedQuery` (lines 60–88) plus new `CompilationContext` dataclass (~30 lines of new code, ~80 lines total).

**Tests to write first (`tests/services/query_forge/test_types.py`):**
- `CompilationContext` can be constructed and is immutable (setting a field raises `FrozenInstanceError`)
- `CompilationContext` with empty dicts is valid
- Each result dataclass (`ForgeCompiledQuery`, `QueryForgeRunResult`, `QueryForgePreparedQuery`) has the correct fields and is frozen
- Existing imports from `query_forge_service` continue to resolve (shim imports from new location)

**Done when:** All type imports resolve from `query_forge/types.py`; `service.py` imports from there; existing import path via `query_forge_service` still works.

---

### Phase 2 — `sql_utils.py`

**What moves:** `_qf_safe_ident`, `_safe_alias`, `_safe_table_full_name`, `_literal_sql`, `_qf_render_sql` (lines 2670–2761, ~60 lines) — promoted from methods to module-level functions.

**Tests to write first (`tests/services/query_forge/test_sql_utils.py`):**
- `qf_safe_ident` wraps identifiers in backticks and escapes embedded backticks
- `qf_safe_ident` raises on identifiers containing SQL injection characters
- `safe_alias` handles empty string, returns a safe default
- `safe_table_full_name` validates `schema.table` format and rejects malformed names
- `literal_sql` escapes single quotes and returns a string safe for interpolation
- `qf_render_sql` substitutes all named `:param` placeholders with their values
- `qf_render_sql` raises on missing parameters

**Done when:** All five functions live in `sql_utils.py`; `service.py` calls them as module-level imports; methods removed from the class.

---

### Phase 3 — `result_mapper.py`

**What moves:** `_qf_cols_from_json`, `_qf_infer_cols`, `_qf_extract_total`, `_qf_rows_to_dicts` (lines 3607–3678, ~70 lines) — promoted to module-level functions.

**Tests to write first (`tests/services/query_forge/test_result_mapper.py`):**
- `cols_from_json` extracts column definitions from a query JSON dict with aggregations and group-bys
- `cols_from_json` returns empty list for a query JSON with no column definitions
- `infer_cols` derives column names from result row dicts
- `infer_cols` returns empty list for empty rows
- `extract_total` returns the integer count from a COUNT query result row
- `extract_total` returns 0 for an empty result
- `rows_to_dicts` zips column name list with row tuples into dicts
- `rows_to_dicts` handles mismatched column count gracefully

**Done when:** All four functions live in `result_mapper.py`; `run()` calls them as module-level imports; methods removed from the class.

---

### Phase 4 — `normalizers/`

**What moves:** `normalize()` logic (lines 227–519), `_qf_norm_filters` (lines 176–226), `_qf_norm_col_key` (lines 576–607), `_qf_norm_metric_expr` (lines 608–658), static metric helpers (lines 520–575) — decomposed into five normalizer functions plus the `NormalizationPipeline` wrapper (~480 lines total).

**Module breakdown:**

| Module | Normalizer responsibility | Source lines |
|--------|--------------------------|-------------|
| `columns.py` | Column reference key normalization, metric expression validation, static metric helpers | 520–658 |
| `filters.py` | Filter tree normalization, OR-equals collapse to IN | 176–226 |
| `aggregations.py` | Aggregation field validation, sorting normalization | subset of 227–519 |
| `attachments.py` | Value override / attachment field normalization | subset of 227–519 |
| `derived.py` | DataPrep / derived expression validation against domain plan | subset of 227–519 |

**Tests to write first (per normalizer, in `tests/services/query_forge/normalizers/`):**
- `test_normalizers_pipeline.py`: `NormalizationPipeline` threads plan through all normalizers in order; aggregates issues from all stages; debug dict keyed by normalizer name; empty pipeline returns query unchanged
- `test_columns.py`: valid column key passes through; shorthand column ref is expanded; invalid metric function name returns an issue string
- `test_filters.py`: OR-equals collapse to IN; nested filter tree passes through; empty filter returns unchanged query
- `test_aggregations.py`: valid aggregation passes through; missing required field returns issue; unknown sort direction returns issue
- `test_attachments.py`: valid attachment passes through; unknown attachment type returns issue
- `test_derived.py`: valid derived expression passes through; expression referencing unknown column returns issue

**Done when:** `QueryForgeService.__init__` constructs `self._normalization = NormalizationPipeline([...])`. The internal `_normalize()` method calls `self._normalization.run(query_json=raw_query, domain_columns=self._load_domain_column_catalog())`.

---

### Phase 5 — `data_prep_compiler.py`

**What moves:** `_compile_data_prep_meta` (lines 1989–2243), `_build_prep_base_selects` (lines 2581–2669), `_qf_compile_dp_cte` (line 1954), `_render_data_prep_cte` (line 2244), `_dp_ident` (line 2732) (~380 lines).

**Public interface:**

```python
class DataPrepCompiler:
    def compile(
        self,
        *,
        query_json: dict,
        domain_columns: dict,
        workspace_table_ids: list[int],
        alias_by_wt: dict[int, str],
        qf_base_alias: str,
    ) -> tuple[str, CompilationContext]:
        """Return (cte_sql, context) where context carries all five rewrite maps."""
```

`alias_by_wt` (workspace table id → SQL alias) and `qf_base_alias` (the primary table alias string) are computed by the orchestration core before calling this compiler. `_build_prep_base_selects` is an internal helper of `DataPrepCompiler`, not part of its public interface.

**Tests to write first (`tests/services/query_forge/test_data_prep_compiler.py`):**
- Given a query JSON with a known derived expression and a matching domain column dict, `compile()` returns a non-empty CTE SQL string
- The returned `CompilationContext` has `derived_by_exprid` populated from the domain column definitions
- Query JSON with no DataPrep section returns an empty CTE string and an empty `CompilationContext`
- A derived expression referencing a column not in `domain_columns` raises a descriptive `ForgeError`

**Done when:** The orchestration `_compile()` in `service.py` calls `DataPrepCompiler().compile(...)` and receives `(cte_sql, context)`. All five methods removed from `QueryForgeService`.

---

### Phase 6 — `split_ratio_compiler.py`

**What moves:** `_detect_split_ratio_metric` (lines 1582–1646), `_compile_split_ratio_query` (lines 1647–1953) (~370 lines).

**Public interface:**

```python
def is_split_ratio_query(query_json: dict) -> bool:
    """Return True if query_json describes a split ratio metric pattern."""

class SplitRatioCompiler:
    def compile(
        self,
        *,
        query_json: dict,
        domain_columns: dict,
        context: CompilationContext,
        alias_by_wt: dict[int, str],
        qf_base_alias: str,
        mode: str,
        limit: int,
        offset: int,
    ) -> ForgeCompiledQuery:
        """Compile the split ratio metric path into a ForgeCompiledQuery."""
```

**Tests to write first (`tests/services/query_forge/test_split_ratio_compiler.py`):**
- `is_split_ratio_query` returns `True` only for a query JSON containing the split ratio metric structure
- `is_split_ratio_query` returns `False` for standard aggregation queries
- `SplitRatioCompiler.compile` returns a `ForgeCompiledQuery` with non-empty `sql`
- The output SQL contains both the numerator and denominator sub-query fragments
- Missing numerator or denominator raises a descriptive `ForgeError`

**Done when:** The orchestration `_compile()` in `service.py` calls `is_split_ratio_query()` and branches to `SplitRatioCompiler().compile(...)`. Both methods removed from `QueryForgeService`.

---

### Phase 7 — `where_compiler.py`

**What moves:** `_compile_where` (lines 2969–3332), `_is_and_only_filter_tree` (line 1019), `_flatten_and_conditions` (line 1037), `_build_and_filter_tree` (line 1053) (~370 lines).

**Not moved:** `_parse_join_expr` (line 2383) stays in `service.py` — called only from `_compile_join_side`, which remains in the orchestration core. `_effective_filter_mode` (line 2393) stays in `service.py` — called from three orchestration methods (`_compile_where` path, `_required_table_ids_from_query`, `_collect_required_column_keys`); it is passed as a bound method or re-invoked at each call site after extraction.

**Public interface:**

```python
class WhereCompiler:
    def compile(
        self,
        *,
        node: Any,
        context: CompilationContext,
        qf_using_prep: bool,
        qf_base_alias: str,
        alias_by_wt: dict[int, str],
        plan: DomainPlan,
        new_param: Callable[[Any], str],
        force_exists_for_tables: set[int] | None = None,
        severity_table_ids: set[int] | None = None,
    ) -> tuple[str, list[str]]:
        """Return (where_sql, issues). Does not mutate params — uses new_param callback."""
```

`context` absorbs the five rewrite maps that were previously passed as individual parameters. All other orchestration-state parameters (`qf_using_prep`, `qf_base_alias`, `alias_by_wt`, `plan`, `new_param`) are passed explicitly because they are computed by the orchestration core and are not DataPrep-specific.

**Tests to write first (`tests/services/query_forge/test_where_compiler.py`):**
- `equals` filter node produces `col = :p0` with correct parameter binding
- `in` filter produces `col IN (:p0, :p1, ...)` with one parameter per value
- `contains` filter produces `col LIKE :p0`
- `gt` / `lt` / `gte` / `lte` produce correct comparison operators
- `is_null` / `is_not_null` produce `IS NULL` / `IS NOT NULL` with no parameter
- Nested AND tree produces correctly parenthesized SQL
- Nested OR tree produces correctly parenthesized SQL
- Empty filter node (`{}` or `None`) returns empty string and no issues
- Unknown operator raises a descriptive `ForgeError`
- `_is_and_only_filter_tree` returns `True` for a flat AND tree, `False` for one containing OR
- `_flatten_and_conditions` returns a flat list from a nested AND tree

**Done when:** The orchestration `_compile()` in `service.py` instantiates `WhereCompiler` and calls `.compile(...)`. All four methods removed from `QueryForgeService`.

---

### Phase 8 — Slim `service.py` + API cleanup + shim

**What remains in `service.py`:** `__init__` (dependency wiring, pipeline construction), `run()`, `prepare()`, and the internal orchestration methods that coordinate table resolution, join planning, metric compilation, attachment handling, and order-by — all now delegating to the extracted modules. `_parse_join_expr` and `_effective_filter_mode` remain here.

**API changes:**
- `compile()` becomes `_compile()` (internal)
- `normalize()` becomes `_normalize()` (internal)
- `run()` and `prepare()` rename their first parameter from `raw_query` to `query_json`
- `mode` parameter is preserved on both methods

**Route call-site updates (three files):**

| File | Change |
|------|--------|
| `app/features/query_engine/query_api.py:109` | `raw_query=raw` → positional `raw` |
| `app/tasks/skill_runner.py:210` | `raw_query=sql_json` → positional `sql_json` |
| `app/routes/query_analysis_routes.py:357` | `raw_query=sql_json` → positional `sql_json` |

**`query_forge_service.py` becomes:**
```python
from app.services.query_forge.service import QueryForgeService  # noqa: F401
```

**Tests to write first (`tests/services/query_forge/test_service.py`):**
- `QueryForgeService` can be instantiated with a mock executor and domain resolver
- `run()` with a minimal valid query JSON calls `_compile()` and returns a `QueryForgeRunResult`
- `prepare()` returns a `QueryForgePreparedQuery` with non-empty `sql`
- Invalid query JSON causes `_normalize()` to return issues, which surfaces as a `ForgeError` before compilation
- `mode="export"` is passed through to `_compile()` correctly
- Importing `QueryForgeService` from `query_forge_service` still works (shim test)

**Done when:** `service.py` contains no helper function bodies; all tests pass; `query_forge_service.py` is a one-line shim; version bumped.

---

## Testing Strategy

All tests live under `tests/services/query_forge/` mirroring the new package layout:

```
tests/services/query_forge/
    test_types.py
    test_sql_utils.py
    test_result_mapper.py
    normalizers/
        test_normalization_pipeline.py   # NormalizationPipeline runner, issue aggregation, debug keying
        test_columns.py
        test_filters.py
        test_aggregations.py
        test_attachments.py
        test_derived.py
    test_data_prep_compiler.py
    test_split_ratio_compiler.py
    test_where_compiler.py
    test_service.py
```

Tests use real data structures (query JSON dicts, domain column dicts) — not mocks of internal methods. Each test file is written before the corresponding module is created. The `NormalizationPipeline` class itself is tested in `test_normalization_pipeline.py` independently of the individual normalizer modules.

---

## Non-Goals (Repeated for Emphasis)

- No new query features
- No changes to SQL dialect or executor interface
- No changes to the planner domain service
- No ORM or schema changes
- No frontend changes
- No removal of `mode` parameter or change to its semantics
