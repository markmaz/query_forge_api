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

Ten+ methods thread a cluster of five rewrite maps (`derived_by_exprid`, `derived_by_name`,
`rewrite_by_colname`, `rewrite_by_modelid`, `rewrite_by_wt_col`) as individual parameters,
causing parameter explosion across the call graph.

The file's structure closely mirrors `no_code_query_service.py` in the workboard codebase
(confirmed by similarity analysis), making the two hard to evolve independently.

---

## Non-Goals

This refactor must **not**:

- Change SQL dialect or query semantics
- Alter database schema or ORM models
- Introduce new query features or change normalization rules
- Merge query_forge with the planner domain service
- Remove the `mode` parameter from the public API or change its semantics
- Change the executor interface or how `QueryForgeService` receives its executor (injected in `__init__`, not per-call)

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
4. **Normalization** — `normalize()` (lines 227–519), `_qf_norm_filters` (lines 176–226), `_qf_norm_col_key` (lines 576–607), `_qf_norm_metric_expr` (lines 608–658), static metric helpers (lines 520–575)
5. **DataPrep compilation** — `_compile_data_prep_meta` (lines 1989–2243), `_build_prep_base_selects` (lines 2581–2669), `_qf_compile_dp_cte` (line 1954), `_render_data_prep_cte` (line 2244), `_dp_ident` (line 2732)
6. **Split ratio compilation** — `_detect_split_ratio_metric` (lines 1582–1646), `_compile_split_ratio_query` (lines 1647–1953)
7. **WHERE compilation** — `_compile_where` (lines 2969–3332), `_is_and_only_filter_tree` (line 1019), `_flatten_and_conditions` (line 1037), `_build_and_filter_tree` (line 1053)
8. **Orchestration core** — `__init__`, `run`, `prepare`, `compile`, and all remaining table-resolution/join/metric/attachment/order-by methods

**Methods that stay in `service.py`:**

- `_parse_join_expr` (line 2383) — called only from `_compile_join_side`, which stays in the orchestration core.
- `_effective_filter_mode` (line 2393) — called from three orchestration methods: within `_compile_where` (moving to `WhereCompiler`), `_required_table_ids_from_query` (line 2466), and `_collect_required_column_keys` (line 2558). Because two of the three call sites stay in `service.py`, this method stays there. It is passed as a `Callable` argument to `WhereCompiler.compile` so that `where_compiler.py` has no import dependency on `service.py`.
- `_load_domain_column_catalog` (line 898) — existing method taking `plan: DomainPlan`, returns `Dict[tuple[int, str], Dict[str, Any]]`. Stays in `service.py`; called by the normalization pipeline invocation and by the DataPrep compiler call.

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
        __init__.py           # NormalizationPipeline
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

All five fields are required (no defaults). `rewrite_by_wt_col` was previously an optional parameter defaulting to `{}` in `_compile_where` and other methods; it becomes a required field in `CompilationContext` — callers always provide it, using `{}` when DataPrep is inactive. `DataPrepCompiler` builds and returns a fully populated context. The orchestration core passes it as a single argument to `WhereCompiler`, metric compilation, `_col_expr`, etc.

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

Returns `(normalized_query, issues, debug)`. `domain_columns` carries the column catalog needed for validation (equivalent to `capabilities` in the planner domain pipeline — same pattern, different field name reflecting the query-forge domain).

The `NormalizationPipeline` constructor and `run` signature:

```python
class NormalizationPipeline:
    def __init__(
        self,
        normalizers: list[tuple[str, Callable[..., tuple[dict, list[str], dict]]]],
    ) -> None: ...

    def run(
        self,
        *,
        query_json: dict,
        domain_columns: dict,
    ) -> NormalizationPipelineResult: ...
```

Returns a `NormalizationPipelineResult` dataclass with fields `query_json: dict`, `all_issues: list[str]`, `debug: dict[str, Any]` — identical structure to the planner domain result.

The pipeline threads normalizers in order:

```
columns → filters → aggregations → attachments → derived
```

The pipeline instance is constructed once in `QueryForgeService.__init__`. The existing `normalize()` method becomes internal (`_normalize()`), which calls:

```python
result = self._normalization.run(
    query_json=raw_query,
    domain_columns=self._load_domain_column_catalog(plan),
)
```

where `plan` is resolved before normalization via `self._domains.resolve_plan(domain_id=...)`.

### Public API (Phase 8)

The current signatures are:

```python
# Current — callers pass raw_query as keyword, mode as keyword or positional
svc.run(raw_query=raw, mode=mode, limit=limit, offset=offset)          # query_api.py:109
svc.run(raw_query=sql_json, mode="export", limit=..., offset=0)        # skill_runner.py:210
svc.run(raw_query=sql_json, mode="export", limit=500, offset=0)        # query_analysis_routes.py:357
service.prepare(raw_query=sql_json, mode=mode, limit=limit, offset=offset)  # execution_mode_query_builder.py:37
svc.run(q, "preview")                                                   # tests/sql_tester.py:138
svc.run(q, limit=2, offset=0)                                          # tests/test_query_forge_service_compile_extra.py:1131
```

The Phase 8 cleanup renames `raw_query` → `query_json` and makes `mode` keyword-only. `compile()` and `normalize()` become internal (`_compile()`, `_normalize()`). Updated signatures:

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

**Call-site migrations (Phase 8):**

| File | Method | Before | After |
|------|--------|--------|-------|
| `app/features/query_engine/query_api.py:109` | `run` | `svc.run(raw_query=raw, mode=mode, ...)` | `svc.run(raw, mode=mode, ...)` |
| `app/tasks/skill_runner.py:210` | `run` | `svc.run(raw_query=sql_json, mode="export", ...)` | `svc.run(sql_json, mode="export", ...)` |
| `app/routes/query_analysis_routes.py:357` | `run` | `svc.run(raw_query=sql_json, mode="export", ...)` | `svc.run(sql_json, mode="export", ...)` |
| `app/services/execution/execution_mode_query_builder.py:37` | `prepare` | `service.prepare(raw_query=sql_json, mode=mode, ...)` | `service.prepare(sql_json, mode=mode, ...)` |
| `tests/sql_tester.py:138` | `run` | `svc.run(q, "preview")` | `svc.run(q, mode="preview")` |
| `tests/services/test_query_forge_service_compile_extra.py:1131` | `run` | `svc.run(q, limit=2, offset=0)` | no change needed — positional `q` still works |

---

## Phase Breakdown

### Phase 1 — `types.py`

**What moves:** `ForgeCompiledQuery`, `QueryForgeRunResult`, `QueryForgePreparedQuery` (lines 60–88) plus new `CompilationContext` dataclass (~30 lines new, ~80 lines total).

**Tests to write first (`tests/services/query_forge/test_types.py`):**
- `CompilationContext` can be constructed with all five rewrite map fields
- `CompilationContext` is immutable — setting any field raises `FrozenInstanceError`
- `CompilationContext` with empty dicts for all fields is valid
- Each result dataclass (`ForgeCompiledQuery`, `QueryForgeRunResult`, `QueryForgePreparedQuery`) has the correct fields and is frozen
- Importing `QueryForgeService` from `app.services.query_forge_service` still resolves (shim test)

**Done when:** All type imports resolve from `query_forge/types.py`; `service.py` imports from there.

---

### Phase 2 — `sql_utils.py`

**What moves:** `_qf_safe_ident`, `_safe_alias`, `_safe_table_full_name`, `_literal_sql`, `_qf_render_sql` (lines 2670–2761, ~60 lines) — promoted from instance methods to module-level functions.

**Tests to write first (`tests/services/query_forge/test_sql_utils.py`):**
- `qf_safe_ident` wraps an identifier in backticks and escapes embedded backticks
- `qf_safe_ident` raises `ForgeError` on identifiers containing semicolons or other injection characters
- `safe_alias` returns a safe default for empty string input
- `safe_table_full_name` validates `schema.table` format and rejects malformed names
- `literal_sql` escapes single quotes
- `qf_render_sql` substitutes all named `:param` placeholders with their string representations
- `qf_render_sql` raises on a missing parameter key

**Done when:** All five functions live in `sql_utils.py`; `service.py` imports and calls them as module-level functions; methods removed from `QueryForgeService`.

---

### Phase 3 — `result_mapper.py`

**What moves:** `_qf_cols_from_json`, `_qf_infer_cols`, `_qf_extract_total`, `_qf_rows_to_dicts` (lines 3607–3678, ~70 lines) — promoted to module-level functions.

**Tests to write first (`tests/services/query_forge/test_result_mapper.py`):**
- `cols_from_json` extracts column definitions from a query JSON dict with aggregations and group-bys
- `cols_from_json` returns an empty list for a query JSON with no column definitions
- `infer_cols` derives column names from result row dicts
- `infer_cols` returns an empty list for empty rows
- `extract_total` returns the integer count from a COUNT query result row
- `extract_total` returns `0` for an empty result
- `rows_to_dicts` zips a column name list with row tuples into dicts
- `rows_to_dicts` returns empty list for empty input

**Done when:** All four functions live in `result_mapper.py`; `run()` calls them as module-level imports; methods removed from `QueryForgeService`.

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
| `derived.py` | DataPrep / derived expression validation against domain column catalog | subset of 227–519 |

**Tests to write first:**

`tests/services/query_forge/normalizers/test_normalization_pipeline.py`:
- `NormalizationPipeline` with an empty normalizer list returns query unchanged with no issues
- Plan is threaded through normalizers in order (each step sees the previous step's output)
- Issues from all stages are concatenated in order
- Debug dict is keyed by normalizer name; empty debug dicts are excluded
- Optional extra kwargs (`domain_columns`) are forwarded to each normalizer

Per-normalizer test files (`test_columns.py`, `test_filters.py`, `test_aggregations.py`, `test_attachments.py`, `test_derived.py`):
- Pass-through: valid input returns unchanged query and empty issues
- Normalization: shorthand or invalid input is corrected; issue string returned
- Edge cases: missing fields, empty lists, null values handled without raising

**Done when:** `QueryForgeService.__init__` constructs `self._normalization = NormalizationPipeline([...])`. The internal `_normalize()` calls `self._normalization.run(query_json=raw_query, domain_columns=self._load_domain_column_catalog(plan))`.

---

### Phase 5 — `data_prep_compiler.py`

**What moves:** `_compile_data_prep_meta` (lines 1989–2243), `_build_prep_base_selects` (lines 2581–2669), `_qf_compile_dp_cte` (line 1954), `_render_data_prep_cte` (line 2244), `_dp_ident` (line 2732) (~380 lines).

`_build_prep_base_selects` is an internal helper of `DataPrepCompiler`, not part of its public interface.

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

`alias_by_wt` and `qf_base_alias` are computed by the orchestration core before this call. When a query has no DataPrep section, `compile()` returns `("", CompilationContext(derived_by_exprid={}, derived_by_name={}, rewrite_by_colname={}, rewrite_by_modelid={}, rewrite_by_wt_col={}))`.

`DataPrepCompiler`, `SplitRatioCompiler`, and `WhereCompiler` are all stateless — they take no constructor arguments and are instantiated fresh at each call site (`DataPrepCompiler().compile(...)`, `SplitRatioCompiler().compile(...)`, `WhereCompiler().compile(...)`). All dependencies are passed as keyword arguments to `compile()`.

**Tests to write first (`tests/services/query_forge/test_data_prep_compiler.py`):**
- Given a query JSON with a known derived expression and matching `domain_columns`, `compile()` returns a non-empty CTE SQL string
- The returned `CompilationContext` has `derived_by_exprid` populated
- A query JSON with no DataPrep section returns an empty string and an empty `CompilationContext`
- A derived expression referencing a column not in `domain_columns` raises a descriptive `ForgeError`

**Done when:** The orchestration `_compile()` in `service.py` calls `DataPrepCompiler().compile(...)` and receives `(cte_sql, context)`; all five methods removed from `QueryForgeService`.

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
- The output SQL contains both numerator and denominator sub-query fragments
- Missing numerator or denominator raises a descriptive `ForgeError`

**Done when:** The orchestration `_compile()` in `service.py` calls `is_split_ratio_query()` and branches to `SplitRatioCompiler().compile(...)`; both methods removed from `QueryForgeService`.

---

### Phase 7 — `where_compiler.py`

**What moves:** `_compile_where` (lines 2969–3332), `_is_and_only_filter_tree` (line 1019), `_flatten_and_conditions` (line 1037), `_build_and_filter_tree` (line 1053) (~370 lines).

**Not moved:**
- `_parse_join_expr` (line 2383) — stays in `service.py`, called only from `_compile_join_side` in the orchestration core.
- `_effective_filter_mode` (line 2393) — stays in `service.py`. Passed as a `Callable` to `WhereCompiler.compile` so that `where_compiler.py` has no import dependency on `service.py`.

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
        filter_mode_fn: Callable[[DomainPlan, int], str],
        force_exists_for_tables: set[int] | None = None,
        severity_table_ids: set[int] | None = None,
    ) -> tuple[str, list[str]]:
        """Return (where_sql, issues). Uses new_param callback for parameter binding."""
```

`context` absorbs all five rewrite maps (including `rewrite_by_wt_col`, which was previously an optional parameter defaulting to `{}`). `filter_mode_fn` is `self._effective_filter_mode` from `service.py`, passed in at the call site — no import of `service.py` from `where_compiler.py`.

**Tests to write first (`tests/services/query_forge/test_where_compiler.py`):**
- `equals` filter node produces `col = :p0` with correct parameter binding
- `in` filter produces `col IN (:p0, :p1, ...)` with one parameter per value
- `contains` filter produces `col LIKE :p0`
- `gt` / `lt` / `gte` / `lte` produce correct comparison operators
- `is_null` / `is_not_null` produce `IS NULL` / `IS NOT NULL` with no parameter
- Nested AND tree produces correctly parenthesized SQL
- Nested OR tree produces correctly parenthesized SQL
- Empty/`None` filter node returns empty string and no issues
- Unknown operator raises a descriptive `ForgeError`
- `_is_and_only_filter_tree` returns `True` for a flat AND tree, `False` for one containing OR
- `_flatten_and_conditions` returns a flat list from a nested AND tree

**Done when:** The orchestration `_compile()` in `service.py` instantiates `WhereCompiler` and calls `.compile(..., filter_mode_fn=self._effective_filter_mode, ...)`; all four methods removed from `QueryForgeService`.

---

### Phase 8 — Slim `service.py` + API cleanup + shim

**What remains in `service.py`:** `__init__` (dependency wiring, pipeline construction), `run()`, `prepare()`, `_compile()`, `_normalize()`, and the internal orchestration methods for table resolution, join planning, metric compilation, attachment handling, and order-by — all now delegating to the extracted modules. `_parse_join_expr`, `_effective_filter_mode`, and `_load_domain_column_catalog` remain here.

**API changes:**
- `compile()` becomes `_compile()` (internal)
- `normalize()` becomes `_normalize()` (internal)
- `run()` and `prepare()` rename first parameter from `raw_query` to `query_json`
- `mode` becomes keyword-only on both methods

**Call-site migrations:**

| File | Method | Before | After |
|------|--------|--------|-------|
| `app/features/query_engine/query_api.py:109` | `run` | `svc.run(raw_query=raw, mode=mode, ...)` | `svc.run(raw, mode=mode, ...)` |
| `app/tasks/skill_runner.py:210` | `run` | `svc.run(raw_query=sql_json, mode="export", ...)` | `svc.run(sql_json, mode="export", ...)` |
| `app/routes/query_analysis_routes.py:357` | `run` | `svc.run(raw_query=sql_json, mode="export", ...)` | `svc.run(sql_json, mode="export", ...)` |
| `app/services/execution/execution_mode_query_builder.py:37` | `prepare` | `service.prepare(raw_query=sql_json, mode=mode, ...)` | `service.prepare(sql_json, mode=mode, ...)` |
| `tests/sql_tester.py:138` | `run` | `svc.run(q, "preview")` | `svc.run(q, mode="preview")` |
| `tests/services/test_query_forge_service_compile_extra.py:1131` | `run` | `svc.run(q, limit=2, offset=0)` | no change needed |

**`query_forge_service.py` becomes:**
```python
from app.services.query_forge.service import QueryForgeService  # noqa: F401
```

**Tests to write first (`tests/services/query_forge/test_service.py`):**
- `QueryForgeService` can be instantiated with a mock executor and domain resolver
- `run(query_json, mode="preview", ...)` returns a `QueryForgeRunResult`
- `prepare(query_json, mode="preview", ...)` returns a `QueryForgePreparedQuery` with non-empty `sql`
- `run` and `prepare` reject `raw_query` as a keyword argument (verifies the rename)
- `mode` passed as positional raises `TypeError` (verifies keyword-only enforcement)
- `mode="export"` is passed through to `_compile()` correctly
- Invalid query JSON surfaces as a `ForgeError` before compilation
- Importing `QueryForgeService` from `app.services.query_forge_service` still works

**Done when:** `service.py` contains no helper function bodies; all call sites updated; all tests pass; `query_forge_service.py` is a one-line shim; version bumped.

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

Tests use real data structures (query JSON dicts, domain column dicts) — not mocks of internal methods. Each test file is written before the corresponding module is created. `test_normalization_pipeline.py` tests the pipeline runner itself independently of the individual normalizer modules.

---

## Non-Goals (Repeated for Emphasis)

- No new query features
- No changes to SQL dialect or executor interface
- No changes to the planner domain service
- No ORM or schema changes
- No frontend changes
- No removal of `mode` parameter or change to its semantics
