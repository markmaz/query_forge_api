UPDATE planner_rerank_policy_candidate
SET vertical_norm = NULL
WHERE vertical_norm IS NOT NULL;
