# ForgeInsights Frontend Prompt (ADM Pivot Rendering)

Copy/paste this into your frontend coding assistant:

```text
Implement ADM result rendering for ForgeInsights chat so grouped ADM rows are displayed as a pivot-style table in the chat UI.

Context:
- ForgeInsights sends education prompts through plan_domain + execution.
- Backend returns grouped rows (not SQL PIVOT), typically:
  - school_year
  - report_period
  - school_name (optional for by-school)
  - student_unique_id / first_name / last_name (optional for by-student)
  - total_adm (or Total ADM label)
- We want frontend to render these grouped rows as a pivot-style table.

Requirements:
1) Keep existing execution polling flow unchanged.
2) When execution results return, detect ADM shape:
   - has `report_period`
   - has an ADM metric column (case-insensitive match on: total_adm, adm, adm_total, total adm)
3) Build pivot rows in frontend:
   - Pivot columns: report periods (sorted numerically where possible: 1..9, then lexical fallback).
   - Row key dimension priority:
     1) school_name + school_year (if school_name present)
     2) student_unique_id + first_name + last_name + school_year (if student fields present)
     3) school_year only
4) Render:
   - Markdown summary on top (existing assistant message).
   - ADM pivot table below (new component) with sticky first column.
   - Include row total and grand total toggle.
5) Formatting:
   - ADM values: show up to 2 decimals.
   - Empty cells: show "-"
6) UX:
   - Add "Raw rows / Pivot view" toggle.
   - Default to Pivot view when ADM shape is detected.
   - Keep non-ADM results in existing table renderer.

Implementation details (TypeScript):
- Add utility:
  - `isAdmResult(columns, rows): boolean`
  - `buildAdmPivot(rows): { columns: string[]; rows: PivotRow[]; grandTotals: Record<string, number> }`
- Prefer metric key from columns metadata first, then fallback to row keys.
- Defensive parsing:
  - report_period may come as string or number.
  - adm value may come as string or number.

Suggested component API:
- `<AdmPivotTable rows={rows} columns={columns} />`
- Props:
  - `rows: Array<Record<string, unknown>>`
  - `columns: Array<{ key: string; label?: string }>`

Acceptance tests:
1) Given rows grouped by school_year/report_period, UI renders one row per school_year with period columns.
2) Given rows grouped by school_name/report_period, UI renders one row per school_name (+school_year if present).
3) Given rows grouped by student/report_period, UI renders one row per student.
4) Unknown metric name falls back to raw table.
5) Pivot toggle switches between pivot and raw table without re-fetch.
```

