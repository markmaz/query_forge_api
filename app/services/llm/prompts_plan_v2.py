from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Sequence


SLOT_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["intent", "entity", "constraints", "time_phrases"],
    "properties": {
        "intent": {"type": "string", "enum": ["aggregate", "list", "trend", "unknown"]},
        "entity": {"type": "string"},
        "constraints": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["kind", "text", "op", "value_hint", "notes"],
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["demographic", "status", "nativity", "location", "date", "unknown"],
                    },
                    "text": {"type": "string"},
                    "op": {
                        "type": "string",
                        "enum": [
                            "eq",
                            "ne",
                            "in",
                            "not_in",
                            "gt",
                            "gte",
                            "lt",
                            "lte",
                            "contains",
                            "exists",
                            "not_exists",
                            "unknown",
                        ],
                    },
                    "value_hint": {"type": ["string", "null"]},
                    "notes": {"type": ["string", "null"]},
                },
            },
        },
        "time_phrases": {"type": "array", "items": {"type": "string"}},
    },
}

NEXT_ACTIONS_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["next_actions"],
    "properties": {
        "next_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["label", "prompt", "reason", "intent", "dimensions", "filters", "metrics", "confidence"],
                "properties": {
                    "label": {"type": "string"},
                    "prompt": {"type": "string"},
                    "reason": {"type": "string"},
                    "intent": {"type": "string", "enum": ["list", "aggregate", "trend"]},
                    "dimensions": {"type": "array", "items": {"type": "string"}},
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["column_key", "op"],
                            "properties": {
                                "column_key": {"type": "string"},
                                "op": {"type": "string"},
                                "value": {},
                                "values": {"type": "array"},
                            },
                        },
                    },
                    "metrics": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                },
            },
        }
    },
}


def build_system_prompt() -> str:
    return (
        "You are a query planner that returns STRICT JSON only. "
        "Never return prose, markdown, comments, or code fences."
    )


def build_slot_developer_prompt() -> str:
    return (
        "Task: Extract lightweight planning slots AND structured constraint hints.\n"
        "Do NOT choose column_keys. Do NOT invent codes. Do NOT output SQL.\n"
        "If uncertain, keep fields empty rather than guessing.\n"
        "Output JSON with fields: intent, entity, constraints, time_phrases.\n"
        "Constraint object schema:\n"
        "{\n"
        "  \"kind\": \"demographic\" | \"status\" | \"nativity\" | \"location\" | \"date\" | \"unknown\",\n"
        "  \"text\": \"original phrase from prompt\",\n"
        "  \"op\": \"eq\" | \"ne\" | \"in\" | \"not_in\" | \"gt\" | \"gte\" | \"lt\" | \"lte\" | \"contains\" | \"exists\" | \"not_exists\" | \"unknown\",\n"
        "  \"value_hint\": string|null,\n"
        "  \"notes\": string|null\n"
        "}\n"
        "Rules:\n"
        "- If prompt mentions \"born\", \"birth\", \"birth country\", \"not born\", or \"entered the US\", set kind=\"nativity\".\n"
        "  - For \"not born in the US\": op=\"ne\", value_hint=\"United States\", notes=\"nativity:not-born-us\".\n"
        "  - For \"born in the US\": op=\"eq\", value_hint=\"United States\", notes=\"nativity:born-us\".\n"
        "  - For \"entered the US\": op=\"exists\", value_hint=null, notes=\"nativity:entered-us\".\n"
        "- If prompt mentions race/ethnicity terms (black, white, hispanic, etc.), set kind=\"demographic\" with plain-language value_hint.\n"
        "- If prompt asks where a person works (for example: works, worked, employed, teaches, workplace, job), set entity=\"staff\" and intent=\"list\".\n"
        "- If prompt asks where a person goes to school (for example: goes to, attends, enrolled), set entity=\"students\" and intent=\"list\".\n"
        "- Examples:\n"
        "  - \"Show me where Jennifer Gilstrap works\" => entity=\"staff\", intent=\"list\".\n"
        "  - \"What school does Jennifer Gilstrap go to\" => entity=\"students\", intent=\"list\".\n"
        "- If prompt contains city/state patterns (for example \"Clarksville, TN\", \"Clarksville TN\", \"in Clarksville Tennessee\"), set kind=\"location\".\n"
        "  - For city/state patterns, preserve the full location phrase in text and value_hint (for example value_hint=\"Clarksville, TN\").\n"
        "  - Use notes=\"location:city_state\" for city/state constraints.\n"
        "  - Do NOT reinterpret a state token (TN/Tenn./Tennessee) as a county name.\n"
        "- If prompt explicitly says \"county\", keep that as county-oriented location intent (notes=\"location:county\").\n"
        "- For district name phrases, normalize value_hint to the core proper noun and remove generic org suffix words.\n"
        "  - Strip trailing terms like \"school\", \"schools\", \"district\", \"school district\", \"LEA\", \"local education agency\" from value_hint.\n"
        "  - Preserve the geographic proper noun portion (for example keep \"Montgomery County\").\n"
        "  - Example: \"Montgomery County School District\" => value_hint=\"Montgomery County\".\n"
        "- Keep time phrases as raw spans.\n"
        "Return JSON only.\n"
        f"Schema:\n{json.dumps(SLOT_JSON_SCHEMA, ensure_ascii=True)}"
    )


def build_slot_user_prompt(
    *,
    normalized_prompt: str,
    workspace_id: str,
    vertical_norm: str,
    base_domain_id: int,
) -> str:
    return (
        "Extract slot hints from this prompt.\n"
        f"prompt: {normalized_prompt}\n"
        f"workspace_id: {workspace_id}\n"
        f"vertical_norm: {vertical_norm}\n"
        f"base_domain_id: {base_domain_id}\n"
        "Return JSON only."
    )


def build_developer_prompt(
    *,
    schema: Dict[str, Any],
    slot_hints: Mapping[str, Any],
    validation_feedback: str = "",
    retry_hint: str = "",
) -> str:
    feedback_line = f"- Validation feedback from previous attempt: {validation_feedback}\n" if validation_feedback else ""
    retry_hint_line = f"{retry_hint}\n" if retry_hint else ""
    return (
        "You are a query planner that returns STRICT JSON only. Never return prose, markdown, comments, or code fences.\n"
        "You must produce a valid PlanV2 JSON object.\n"
        "Hard rules:\n"
        "- Use exactly one base_domain_id (already provided).\n"
        "- Choose dimensions ONLY from allowed_dimensions column_key values.\n"
        "- Choose filters ONLY from allowed_filter_columns column_key values where filterable=true.\n"
        "- Choose metrics ONLY from allowed_metric_refs.\n"
        "- Never invent new column keys, metric refs, or enum/code values.\n"
        "- Never use a column_key token as a filter value (for example 'wt20.school_name').\n"
        "- Never output values like ALL_CAPS_WITH_UNDERSCORES unless that exact value appears in provided sample/enum lists (none are provided here).\n"
        "- group_by must match selects.dimensions column_keys in the same order.\n"
        "Filter binding rules (VERY IMPORTANT):\n"
        "- When a constraint relates to 'born', 'birth', 'birth country', or 'entered the US':\n"
        "  - Prefer these columns (in order) if present in allowed_dimensions:\n"
        "    1) any column_key containing '.birth_country'\n"
        "    2) any column_key containing '.birth_date' (ONLY if prompt asks born before/after a date)\n"
        "    3) any column_key containing '.date_entered_us'\n"
        "  - Do NOT use race_ethnicity for nativity/birth constraints.\n"
        "- When a constraint relates to race/ethnicity terms (black, white, hispanic):\n"
        "  - Prefer a column_key containing '.race_ethnicity' or '.has_hispanic_latino_ethnicity'.\n"
        "DISAMBIGUATION RULES (IMPORTANT):\n"
        "- Users often say \"<X> County district\" meaning the school district (LEA), not the geographic county.\n"
        "- If the user uses words like: \"district\", \"school district\", \"LEA\", \"local education agency\":\n"
        "  - Map the district name mentioned in the prompt to the LEA/district name column (e.g., lea_name).\n"
        "  - Normalize the district filter value to the core proper noun by removing generic suffix words.\n"
        "  - Remove terms such as \"school\", \"schools\", \"district\", \"school district\", \"LEA\", \"local education agency\" from the value.\n"
        "  - Example: \"Montgomery County School District\" => filter lea_name = \"Montgomery County\".\n"
        "  - Do NOT map it to a county column just because it contains the word \"County\".\n"
        "  - Example: \"Davidson County district\" => filter lea_name = \"Davidson County\".\n"
        "- Only filter by county columns (e.g., name_of_county) when the user clearly asks for geographic county,\n"
        "  such as \"schools in Davidson County\" / \"located in Davidson County\" / \"county is Davidson\".\n"
        "- If both county and district are mentioned, treat them as separate concepts: use lea_name for the district name and name_of_county for geography.\n"
        "CITY/STATE RULES (IMPORTANT):\n"
        "- If the user provides a city/state pair (for example \"Clarksville, TN\"), treat it as city+state, not county.\n"
        "- If an allowed city column exists, you MUST use it for the city token (column_key/column_name containing '.city', '_city', or 'city_name').\n"
        "- Prefer a geographic state column for the state token (containing '.state', 'state_code', 'state_abbr', or 'state_name').\n"
        "- Do NOT convert a city token to county unless the prompt explicitly says \"county\".\n"
        "- NEVER map a state token (for example TN, Tenn., Tennessee) into a county column such as name_of_county.\n"
        "- For geographic location filters, do NOT use state_school_code when state_code/state_abbr/state_name is available.\n"
        "- If city column exists but no state column exists, filter by city only (do not force a county fallback).\n"
        "- Do NOT use school_name as a proxy for city unless the user explicitly asks about school names matching text.\n"
        "- Do NOT include SQL wildcard characters in filter values (no '%' in values).\n"
        "- Example: \"Show schools in Clarksville, TN\" => city filter = \"Clarksville\" AND state filter = \"TN\".\n"
        "- Example: If wt20.city is available and user asks \"Show schools in Clarksville, TN\", use wt20.city = \"Clarksville\".\n"
        "- If city/state columns are unavailable in allowed_filter_columns, use the closest allowed location columns and explain the fallback in debug.reasons.filters.\n"
        "PROPER NOUN FILTER BINDING RULES:\n"
        "- For prompts like \"staff for <School Name>\" or \"teachers at <School Name>\", bind the proper noun to school_name when available.\n"
        "- Do NOT bind human-readable school names to technical key fields (for example k_school) unless the user explicitly asks for internal keys/codes.\n"
        "- Example: \"Show me all the staff for Rossview Elementary\" => filter school_name = \"Rossview Elementary\" (not k_school).\n"
        "- For staff role/title requests (for example principal, assistant principal, counselor, teacher), prefer human-readable role/title columns (position_title, classroom_position, job_title) over classification/code fields.\n"
        "- Do NOT use staff_classification for role-title filtering unless the user explicitly asks for classification/code values.\n"
        "- Example: \"Who is the principal at Rossview Elementary\" => filter school_name = \"Rossview Elementary\" and position_title = \"Principal\" (not staff_classification).\n"
        "Value rules:\n"
        "- Use plain-language values from the prompt whenever possible (e.g., 'United States', 'Black').\n"
        "- If the exact stored value is unknown, still use the plain-language value rather than inventing a coded token.\n"
        "- For person-name columns, prefer canonical first_name/last_name over preferred_first_name/preferred_last_name by default.\n"
        "- Use preferred_first_name/preferred_last_name only when the user explicitly asks for preferred names.\n"
        "Selection rules:\n"
        "- Use slot_hints intent/entity signals when present.\n"
        "- If user says 'by <dimension>' or 'grouped by <dimension>', add that dimension to selects/group_by and do not create an equals filter unless a literal value is explicitly requested.\n"
        "- If user says 'top N' or 'bottom N', set grouping.limit to N and rank by the most relevant allowed metric.\n"
        "- For sales prompts with ranking, prefer a sales/revenue metric when available.\n"
        "- For relative time phrases ('this month', 'last month', 'this year', 'last year'), anchor to current date and avoid stale literal month/year values.\n"
        "- If slot_hints.constraints includes notes starting with 'semantic_alias:', treat value_hint as canonical and prefer that value in filters.\n"
        "- Intent/entity disambiguation: prompts about where someone works/employment/teaching should use staff entity/domain; prompts about where someone attends/goes to school should use student entity/domain.\n"
        "- Few-shot disambiguation examples:\n"
        "  - User: \"Show me where Jennifer Gilstrap works\"\n"
        "    Expected: choose staff-oriented domain (not student demographics), filter person by staff first_name/last_name columns, and return school/LEA workplace columns.\n"
        "  - User: \"What school does Jennifer Gilstrap go to\"\n"
        "    Expected: choose student-oriented domain, filter person by student first_name/last_name columns, and return school enrollment columns.\n"
        "- Include at least one filter when constraints exist.\n"
        "- Before emitting the final JSON, briefly decide (internally) whether each proper noun filter refers to a district/LEA name vs a geographic county.\n"
        "- Do not output the rationale field; only use it to choose the correct column_key.\n"
        "ADM (Average Daily Membership) Rules:\n"
        "- If the prompt asks for ADM/base ADM/average daily membership, treat it as an aggregate request unless the user explicitly asks for a raw row listing.\n"
        "- Prefer a SUM metric over the normalized ADM field (for example normalized_adm) when available.\n"
        "- If allowed filter columns include is_primary_school, you MAY apply is_primary_school = true only for broad ADM summaries (district/school/time rollups).\n"
        "- If allowed filter columns include grade_level_adm, you MAY exclude placeholders with grade_level_adm NOT IN ['P3','P4'] only for broad ADM summaries when user did not request pre-k.\n"
        "- Do NOT auto-add is_primary_school or grade_level_adm filters for person-specific prompts (for example named student/staff requests) unless the user explicitly asks for those constraints.\n"
        "- If user specifies school year, apply a school_year filter.\n"
        "- If user asks by report period, include report_period in grouping.group_by.\n"
        "- If user asks by school, include school_name (or closest school label column) in grouping.group_by.\n"
        "- If user asks by student, include student identity dimensions in grouping.group_by.\n"
        "- SQL PIVOT is not part of PlanV2/SQL JSON contract; represent pivot requests as grouped rows (for example group by school_year + report_period) so client can pivot for display.\n"
        "ADM Examples:\n"
        "- Example: \"Show ADM by report period for 2026\"\n"
        "  {\n"
        "    \"intent\": \"aggregate\",\n"
        "    \"selects\": {\n"
        "      \"dimensions\": [\n"
        "        {\"column_key\": \"wtXX.school_year\"},\n"
        "        {\"column_key\": \"wtXX.report_period\"}\n"
        "      ],\n"
        "      \"metrics\": [{\"metric_ref\": \"domain_metric:adm_total\"}]\n"
        "    },\n"
        "    \"filters\": [\n"
        "      {\"column_key\": \"wtXX.is_primary_school\", \"op\": \"=\", \"value\": true},\n"
        "      {\"column_key\": \"wtXX.school_year\", \"op\": \"=\", \"value\": \"2026\"},\n"
        "      {\"column_key\": \"wtXX.grade_level_adm\", \"op\": \"not_in\", \"values\": [\"P3\", \"P4\"]}\n"
        "    ],\n"
        "    \"grouping\": {\n"
        "      \"group_by\": [\"wtXX.school_year\", \"wtXX.report_period\"],\n"
        "      \"order_by\": [{\"by\": \"wtXX.report_period\", \"dir\": \"asc\"}]\n"
        "    }\n"
        "  }\n"
        "- Example: \"Show ADM by school for 2026\"\n"
        "  {\n"
        "    \"intent\": \"aggregate\",\n"
        "    \"selects\": {\n"
        "      \"dimensions\": [{\"column_key\": \"wtXX.school_name\"}],\n"
        "      \"metrics\": [{\"metric_ref\": \"domain_metric:adm_total\"}]\n"
        "    },\n"
        "    \"filters\": [\n"
        "      {\"column_key\": \"wtXX.is_primary_school\", \"op\": \"=\", \"value\": true},\n"
        "      {\"column_key\": \"wtXX.school_year\", \"op\": \"=\", \"value\": \"2026\"},\n"
        "      {\"column_key\": \"wtXX.grade_level_adm\", \"op\": \"not_in\", \"values\": [\"P3\", \"P4\"]}\n"
        "    ],\n"
        "    \"grouping\": {\n"
        "      \"group_by\": [\"wtXX.school_name\"],\n"
        "      \"order_by\": [{\"by\": \"wtXX.school_name\", \"dir\": \"asc\"}]\n"
        "    }\n"
        "  }\n"
        "School Listing Output Contract:\n"
        "- If this is a school listing request (entity is schools and intent is list, or prompt asks to find/list/show schools), enforce this output contract.\n"
        "- For school listing output, selects.dimensions MUST include these columns in this order when allowed:\n"
        "  1) a school name column (prefer wt20.school_name)\n"
        "  2) a district/LEA name column (prefer wt20.lea_name)\n"
        "  3) a school number column (prefer wt20.school_number)\n"
        "- If all three are allowed, they should be the first three dimensions in that exact order.\n"
        "- If one is unavailable in allowed dimensions, use the closest allowed equivalent and explain fallback in debug.reasons.domain.\n"
        "- Avoid technical/code-only identifiers (for example nces_school_code, k_school) in listing output unless the user explicitly asks for codes/IDs.\n"
        "- If the user asks for additional school fields, append them AFTER the required school listing columns.\n"
        "- If prompt intent is aggregate (e.g., 'how many schools'), this is NOT a listing: use metrics and do not force school listing dimensions.\n"
        "- Example: \"Show schools in Clarksville, TN\" => dimensions should start with school_name, lea_name, school_number (if allowed), then apply location filters.\n"
        "Student Listing Output Contract:\n"
        "- If this is a student listing request (entity is students and intent is list, or prompt asks to find/list/show students), enforce this output contract.\n"
        "- For student listing output, selects.dimensions MUST start with exactly these three column keys in this order:\n"
        "  1) wt24.student_unique_id\n"
        "  2) wt24.first_name\n"
        "  3) wt24.last_name\n"
        "- For student listing output, grouping.group_by MUST contain the same three columns in the same order.\n"
        "- Do NOT use wt24.k_student, wt24.k_student_xyear, or other technical keys in listing outputs unless the user explicitly asks for internal/technical keys.\n"
        "- If the user asks for additional student fields (grade, gender, etc.), append those AFTER the required three columns.\n"
        "- If prompt intent is aggregate (e.g., 'how many students', 'count students', 'number of students'), this is NOT a listing: choose intent='aggregate', use metrics, and do NOT force the three listing dimensions.\n"
        "Validation-aware behavior for student listing contract:\n"
        "- Only choose dimensions/filters that are allowed in capabilities.\n"
        "- If one of wt24.student_unique_id / wt24.first_name / wt24.last_name is not allowed, retry by choosing closest allowed equivalents:\n"
        "  - identifier fallback: any allowed dimension ending with '.student_unique_id', then '.k_student', then '.k_student_xyear'.\n"
        "  - first-name fallback: any allowed dimension ending with '.first_name'.\n"
        "  - last-name fallback: any allowed dimension ending with '.last_name'.\n"
        "- If the contract still cannot be met with allowed columns, return valid PlanV2 JSON and explain in debug.reasons.domain why the contract could not be fully met.\n"
        "Student Listing Output Contract Examples:\n"
        "- Example 1: \"List students with last name Black\"\n"
        "  {\n"
        "    \"intent\": \"list\",\n"
        "    \"selects\": {\n"
        "      \"dimensions\": [\n"
        "        {\"column_key\": \"wt24.student_unique_id\"},\n"
        "        {\"column_key\": \"wt24.first_name\"},\n"
        "        {\"column_key\": \"wt24.last_name\"}\n"
        "      ],\n"
        "      \"metrics\": []\n"
        "    },\n"
        "    \"filters\": [\n"
        "      {\"column_key\": \"wt24.last_name\", \"op\": \"=\", \"value\": \"Black\"}\n"
        "    ],\n"
        "    \"grouping\": {\n"
        "      \"group_by\": [\"wt24.student_unique_id\", \"wt24.first_name\", \"wt24.last_name\"],\n"
        "      \"order_by\": []\n"
        "    }\n"
        "  }\n"
        "- Example 2: \"Show students not born in the US\"\n"
        "  {\n"
        "    \"intent\": \"list\",\n"
        "    \"selects\": {\n"
        "      \"dimensions\": [\n"
        "        {\"column_key\": \"wt24.student_unique_id\"},\n"
        "        {\"column_key\": \"wt24.first_name\"},\n"
        "        {\"column_key\": \"wt24.last_name\"}\n"
        "      ],\n"
        "      \"metrics\": []\n"
        "    },\n"
        "    \"filters\": [\n"
        "      {\"column_key\": \"wt24.birth_country\", \"op\": \"!=\", \"value\": \"United States\"}\n"
        "    ],\n"
        "    \"grouping\": {\n"
        "      \"group_by\": [\"wt24.student_unique_id\", \"wt24.first_name\", \"wt24.last_name\"],\n"
        "      \"order_by\": []\n"
        "    }\n"
        "  }\n"
        "- Example 3: \"Find students named Holden Black\"\n"
        "  {\n"
        "    \"intent\": \"list\",\n"
        "    \"selects\": {\n"
        "      \"dimensions\": [\n"
        "        {\"column_key\": \"wt24.student_unique_id\"},\n"
        "        {\"column_key\": \"wt24.first_name\"},\n"
        "        {\"column_key\": \"wt24.last_name\"}\n"
        "      ],\n"
        "      \"metrics\": []\n"
        "    },\n"
        "    \"filters\": [\n"
        "      {\"column_key\": \"wt24.first_name\", \"op\": \"=\", \"value\": \"Holden\"},\n"
        "      {\"column_key\": \"wt24.last_name\", \"op\": \"=\", \"value\": \"Black\"}\n"
        "    ],\n"
        "    \"grouping\": {\n"
        "      \"group_by\": [\"wt24.student_unique_id\", \"wt24.first_name\", \"wt24.last_name\"],\n"
        "      \"order_by\": []\n"
        "    }\n"
        "  }\n"
        "- Example 4: \"List students in grade 9\"\n"
        "  {\n"
        "    \"intent\": \"list\",\n"
        "    \"selects\": {\n"
        "      \"dimensions\": [\n"
        "        {\"column_key\": \"wt24.student_unique_id\"},\n"
        "        {\"column_key\": \"wt24.first_name\"},\n"
        "        {\"column_key\": \"wt24.last_name\"},\n"
        "        {\"column_key\": \"wt24.grade_level\"}\n"
        "      ],\n"
        "      \"metrics\": []\n"
        "    },\n"
        "    \"filters\": [\n"
        "      {\"column_key\": \"wt24.grade_level\", \"op\": \"=\", \"value\": 9}\n"
        "    ],\n"
        "    \"grouping\": {\n"
        "      \"group_by\": [\"wt24.student_unique_id\", \"wt24.first_name\", \"wt24.last_name\", \"wt24.grade_level\"],\n"
        "      \"order_by\": []\n"
        "    }\n"
        "  }\n"
        "- Negative example: \"How many students are not born in the US?\"\n"
        "  {\n"
        "    \"intent\": \"aggregate\",\n"
        "    \"selects\": {\n"
        "      \"dimensions\": [],\n"
        "      \"metrics\": [{\"metric_ref\": \"domain_metric:count_students\"}]\n"
        "    },\n"
        "    \"filters\": [\n"
        "      {\"column_key\": \"wt24.birth_country\", \"op\": \"!=\", \"value\": \"United States\"}\n"
        "    ],\n"
        "    \"grouping\": {\n"
        "      \"group_by\": [],\n"
        "      \"order_by\": []\n"
        "    }\n"
        "  }\n"
        f"{feedback_line}"
        f"{retry_hint_line}"
        "Return PlanV2 JSON only.\n"
        f"Schema:\n{json.dumps(schema, ensure_ascii=True)}"
    )


def build_user_prompt(
    *,
    normalized_prompt: str,
    workspace_id: str,
    vertical_norm: str,
    base_domain: Mapping[str, Any],
    capabilities: Mapping[str, Sequence[Mapping[str, Any]]],
    schema: Dict[str, Any],
    slot_hints: Mapping[str, Any],
) -> str:
    dimensions = list(capabilities.get("dimensions") or [])
    time_columns = list(capabilities.get("time_columns") or [])
    domain_metrics = list(capabilities.get("domain_metrics") or [])
    user_metrics = list(capabilities.get("user_metrics") or [])
    overlay_metrics = list(capabilities.get("overlay_metrics") or [])
    allowed_metric_refs = [
        ref
        for ref in (
            [f"domain_metric:{str(item.get('metric_key') or '').strip().lower()}" for item in domain_metrics]
            + [f"user_metric:{str(item.get('metric_id') or item.get('id') or '').strip().lower()}" for item in user_metrics]
            + [f"overlay:{str(item.get('overlay_key') or '').strip().lower()}" for item in overlay_metrics]
        )
        if ":" in ref and not ref.endswith(":")
    ]

    return (
        "Now build PlanV2 for:\n"
        f"prompt: {normalized_prompt}\n"
        f"workspace_id: {workspace_id}\n"
        f"vertical_norm: {vertical_norm}\n"
        f"base_domain: {json.dumps(dict(base_domain), ensure_ascii=True)}\n"
        f"slot_hints: {json.dumps(dict(slot_hints), ensure_ascii=True)}\n"
        f"allowed_dimensions: {json.dumps(dimensions, ensure_ascii=True)}\n"
        f"allowed_filter_columns: {json.dumps(list(capabilities.get('filter_columns') or []), ensure_ascii=True)}\n"
        f"allowed_time_columns: {json.dumps(time_columns, ensure_ascii=True)}\n"
        f"allowed_domain_metrics: {json.dumps(domain_metrics, ensure_ascii=True)}\n"
        f"allowed_user_metrics: {json.dumps(user_metrics, ensure_ascii=True)}\n"
        f"allowed_overlay_metrics: {json.dumps(overlay_metrics, ensure_ascii=True)}\n"
        f"allowed_metric_refs: {json.dumps(allowed_metric_refs, ensure_ascii=True)}\n"
        f"schema: {json.dumps(schema, ensure_ascii=True)}\n"
        "Return PlanV2 JSON only."
    )


def build_json_repair_prompt(*, schema: Dict[str, Any], broken_json: str) -> str:
    return (
        "Fix this payload to valid PlanV2 JSON. Output JSON only.\n"
        f"Schema: {json.dumps(schema, ensure_ascii=True)}\n"
        f"Broken JSON: {broken_json[:12000]}"
    )


def build_next_actions_developer_prompt() -> str:
    return (
        "Task: Generate smart follow-up suggestions for the same analytics domain.\n"
        "Output JSON only with key next_actions.\n"
        "Hard constraints:\n"
        "- Use ONLY allowed column_key values in dimensions/filters.\n"
        "- Use ONLY allowed metric refs in metrics.\n"
        "- Stay strictly in the current domain context; do not suggest cross-domain analysis.\n"
        "- Keep user context from the current plan (existing filter intent and scope) when appropriate.\n"
        "- Suggestions must be practical and relatable for school/district data users.\n"
        "- No SQL, no table IDs, no internal debug text.\n"
        "- Return 2 to 4 suggestions.\n"
        "Few-shot example A:\n"
        "Input context: current prompt=\"Show me all schools in Clarksville, TN\"; "
        "allowed dimensions include school_name, lea_name, school_type; "
        "allowed filters include city,state_code,school_type; allowed metrics include domain_metric:enrollment_count.\n"
        "Good outputs:\n"
        "1) label=\"Enrollment by school\", prompt=\"Show enrollment count by school in Clarksville, TN\", "
        "intent=\"aggregate\", dimensions=[\"wt20.school_name\"], filters city/state, metrics=[\"domain_metric:enrollment_count\"].\n"
        "2) label=\"Schools by district\", prompt=\"Show schools grouped by district in Clarksville, TN\", "
        "intent=\"list\" or \"aggregate\", dimensions include district + school, filters city/state.\n"
        "Few-shot example B:\n"
        "Input context: current prompt=\"Show me the principal at Barksdale Elementary\"; "
        "allowed dimensions include school_name, first_name, last_name, position_title; "
        "allowed filters include school_name, position_title.\n"
        "Good outputs:\n"
        "1) label=\"Assistant principals\", prompt=\"Show assistant principals at Barksdale Elementary\", "
        "filters include school_name + position_title.\n"
        "2) label=\"All staff roles\", prompt=\"Show staff at Barksdale Elementary grouped by position title\", "
        "dimensions include position_title.\n"
        "Return JSON only.\n"
        f"Schema:\n{json.dumps(NEXT_ACTIONS_JSON_SCHEMA, ensure_ascii=True)}"
    )


def build_next_actions_user_prompt(
    *,
    payload: Mapping[str, Any],
) -> str:
    return (
        "Generate next action suggestions for this completed plan context.\n"
        f"input: {json.dumps(dict(payload), ensure_ascii=True)}\n"
        "Return JSON only."
    )


__all__ = [
    "build_developer_prompt",
    "build_json_repair_prompt",
    "build_next_actions_developer_prompt",
    "build_next_actions_user_prompt",
    "build_slot_developer_prompt",
    "build_slot_user_prompt",
    "build_system_prompt",
    "build_user_prompt",
    "NEXT_ACTIONS_JSON_SCHEMA",
    "SLOT_JSON_SCHEMA",
]
