# Goal: Troubleshoot Planner Output

## Audience

Analysts and domain administrators investigating why the planner returned an unexpected query plan.

## What you need

- Access to the plan response (the structured JSON output in Query Studio)
- Optionally: access to admin pipeline profiles

## Steps

### Step 1: Check which domain was selected

The planner explanation tells you which domain was selected and why. Review:
- Was the correct domain selected? If not, see [troubleshooting/wrong-domain-selected.md](../troubleshooting/wrong-domain-selected.md).
- Was the right set of tables included?

### Step 2: Check which concepts were resolved

The explanation shows which semantic concepts were matched for your prompt. Review:
- Were the concepts you intended matched?
- Were any concepts missed (leading to missing columns)?
- Are there conflicting aliases that caused the wrong concept to match?

If concept resolution is wrong, update the semantic registry (aliases, column maps).

### Step 3: Inspect the debug trace (admin)

If admin access is available, retrieve the pipeline trace:
`GET /api/v1/admin/pipeline-profiles/{trace_id}` — returns a step-by-step trace of the planner execution including timings, intermediate scores, and which signals were extracted.

The `trace_id` is returned in the plan response when `QF_PLAN_DOMAIN_PIPELINE_TRACE_ENABLED` is set.

### Step 4: Check normalization

The planner normalizes the prompt through entity, metric, and time normalizers before sending to the LLM. If a prompt term was not recognized, it may have been dropped. Check:
- Are time phrases being normalized correctly?
- Are entity names recognized?

### Step 5: Check LLM output

The LLM is asked to produce a structured plan (schema v2 format). If the LLM output is malformed or incomplete, the planner normalizes and validates it before returning.

Look for any `validation_errors` or `norm_debug` fields in the plan response (NEEDS_VERIFICATION: exact field names).

### Step 6: Review next actions

If next actions are enabled, check whether the suggested follow-up queries expose what the planner understood about the intent. Next actions are generated from the same context as the main plan.

### Step 7: Submit prompt feedback

If you believe the plan was consistently wrong, submit feedback via `POST /api/v1/prompt-feedback`. This feeds the feedback learning pipeline.

## Common issues

- Wrong domain — [troubleshooting/wrong-domain-selected.md](../troubleshooting/wrong-domain-selected.md)
- No results — [troubleshooting/no-query-results.md](../troubleshooting/no-query-results.md)
- Ambiguous mapping — [troubleshooting/mapping-ambiguity.md](../troubleshooting/mapping-ambiguity.md)
- LLM error — [troubleshooting/llm-failure.md](../troubleshooting/llm-failure.md)

## Related docs

- [Concepts: Planner](../concepts/planner.md)
- [Architecture: Planner Pipeline](../architecture/planner-pipeline.md)

## Source grounding
- STATUS: CODE_CONFIRMED (pipeline trace routes), NEEDS_VERIFICATION (exact debug field names in response)
- Sources:
  - `app/routes/admin_routes.py` (PipelineProfileList, PipelineProfileDetail)
  - `app/routes/prompt_feedback.py`
  - `app/services/planner_domain/service.py`
