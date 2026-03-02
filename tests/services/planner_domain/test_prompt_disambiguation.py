from __future__ import annotations

from app.services.llm.prompts_plan_v2 import build_developer_prompt, build_slot_developer_prompt
from app.services.planner_domain.schema_v2 import plan_v2_json_schema


def test_plan_v2_prompt_contains_district_county_disambiguation_rules() -> None:
    prompt = build_developer_prompt(
        schema=plan_v2_json_schema(),
        slot_hints={"intent": "aggregate", "constraints": [], "time_phrases": []},
    )
    slot_prompt = build_slot_developer_prompt()

    assert "DISAMBIGUATION RULES (IMPORTANT):" in prompt
    assert '"Davidson County district" => filter lea_name = "Davidson County".' in prompt
    assert '"Montgomery County School District" => filter lea_name = "Montgomery County".' in prompt
    assert "Normalize the district filter value to the core proper noun by removing generic suffix words." in prompt
    assert "Remove terms such as \"school\", \"schools\", \"district\", \"school district\", \"LEA\", \"local education agency\" from the value." in prompt
    assert "Do NOT map it to a county column just because it contains the word \"County\"." in prompt
    assert "Only filter by county columns" in prompt
    assert "briefly decide (internally) whether each proper noun filter refers to a district/LEA name vs a geographic county." in prompt
    assert "Do not output the rationale field; only use it to choose the correct column_key." in prompt
    assert "CITY/STATE RULES (IMPORTANT):" in prompt
    assert 'If the user provides a city/state pair (for example "Clarksville, TN"), treat it as city+state, not county.' in prompt
    assert 'Do NOT convert a city token to county unless the prompt explicitly says "county".' in prompt
    assert 'Example: "Show schools in Clarksville, TN" => city filter = "Clarksville" AND state filter = "TN".' in prompt
    assert "If an allowed city column exists, you MUST use it for the city token" in prompt
    assert "NEVER map a state token (for example TN, Tenn., Tennessee) into a county column such as name_of_county." in prompt
    assert "For geographic location filters, do NOT use state_school_code when state_code/state_abbr/state_name is available." in prompt
    assert "If city column exists but no state column exists, filter by city only (do not force a county fallback)." in prompt
    assert "Do NOT include SQL wildcard characters in filter values (no '%' in values)." in prompt
    assert 'Example: If wt20.city is available and user asks "Show schools in Clarksville, TN", use wt20.city = "Clarksville".' in prompt
    assert "PROPER NOUN FILTER BINDING RULES:" in prompt
    assert 'For prompts like "staff for <School Name>" or "teachers at <School Name>", bind the proper noun to school_name when available.' in prompt
    assert "Do NOT bind human-readable school names to technical key fields (for example k_school) unless the user explicitly asks for internal keys/codes." in prompt
    assert 'Example: "Show me all the staff for Rossview Elementary" => filter school_name = "Rossview Elementary" (not k_school).' in prompt
    assert "For staff role/title requests (for example principal, assistant principal, counselor, teacher), prefer human-readable role/title columns" in prompt
    assert "Do NOT use staff_classification for role-title filtering unless the user explicitly asks for classification/code values." in prompt
    assert 'Example: "Who is the principal at Rossview Elementary" => filter school_name = "Rossview Elementary" and position_title = "Principal" (not staff_classification).' in prompt
    assert "For person-name columns, prefer canonical first_name/last_name over preferred_first_name/preferred_last_name by default." in prompt
    assert "Use preferred_first_name/preferred_last_name only when the user explicitly asks for preferred names." in prompt
    assert "If slot_hints.constraints includes notes starting with 'semantic_alias:', treat value_hint as canonical and prefer that value in filters." in prompt
    assert "If prompt asks where a person works" in slot_prompt
    assert "set entity=\"staff\" and intent=\"list\"" in slot_prompt
    assert "If prompt asks where a person goes to school" in slot_prompt
    assert "set entity=\"students\" and intent=\"list\"" in slot_prompt
    assert '"Show me where Jennifer Gilstrap works" => entity="staff", intent="list".' in slot_prompt
    assert '"What school does Jennifer Gilstrap go to" => entity="students", intent="list".' in slot_prompt
    assert '"Montgomery County School District" => value_hint="Montgomery County".' in slot_prompt
    assert "prompts about where someone works/employment/teaching should use staff entity/domain" in prompt
    assert 'User: "Show me where Jennifer Gilstrap works"' in prompt
    assert "Expected: choose staff-oriented domain (not student demographics)" in prompt
    assert "School Listing Output Contract:" in prompt
    assert "For school listing output, selects.dimensions MUST include these columns in this order when allowed:" in prompt
    assert "1) a school name column (prefer wt20.school_name)" in prompt
    assert "2) a district/LEA name column (prefer wt20.lea_name)" in prompt
    assert "3) a school number column (prefer wt20.school_number)" in prompt
    assert "Avoid technical/code-only identifiers (for example nces_school_code, k_school) in listing output unless the user explicitly asks for codes/IDs." in prompt
