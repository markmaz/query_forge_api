UPDATE planner_semantic_join_policy
   SET scope_type = CASE
       WHEN scope_type = 'vertical' THEN 'global'
       ELSE scope_type
   END,
       scope_vertical_norm = NULL
 WHERE scope_type = 'vertical'
    OR scope_vertical_norm IS NOT NULL;

ALTER TABLE planner_semantic_join_policy
  DROP INDEX uidx_semantic_join_policy_scope,
  DROP INDEX idx_psjp_scope,
  DROP COLUMN scope_vertical_norm,
  ADD UNIQUE KEY uidx_semantic_join_policy_scope (policy_key, scope_workspace_id),
  ADD KEY idx_psjp_scope (scope_workspace_id);

UPDATE planner_capability_packing_policy
   SET scope_type = CASE
       WHEN scope_type = 'vertical' THEN 'global'
       ELSE scope_type
   END,
       scope_vertical_norm = NULL
 WHERE scope_type = 'vertical'
    OR scope_vertical_norm IS NOT NULL;

ALTER TABLE planner_capability_packing_policy
  DROP INDEX uidx_capability_packing_policy_scope,
  DROP INDEX idx_pcpp_scope,
  DROP COLUMN scope_vertical_norm,
  ADD UNIQUE KEY uidx_capability_packing_policy_scope (policy_key, scope_workspace_id),
  ADD KEY idx_pcpp_scope (scope_workspace_id);

UPDATE planner_concept_scoring_policy
   SET scope_type = CASE
       WHEN scope_type = 'vertical' THEN 'global'
       ELSE scope_type
   END,
       scope_vertical_norm = NULL
 WHERE scope_type = 'vertical'
    OR scope_vertical_norm IS NOT NULL;

ALTER TABLE planner_concept_scoring_policy
  DROP INDEX uidx_concept_scoring_policy_scope,
  DROP INDEX idx_pcsp_scope,
  DROP COLUMN scope_vertical_norm,
  ADD UNIQUE KEY uidx_concept_scoring_policy_scope (policy_key, scope_workspace_id),
  ADD KEY idx_pcsp_scope (scope_workspace_id);

UPDATE planner_semantic_projection_policy
   SET scope_type = CASE
       WHEN scope_type = 'vertical' THEN 'global'
       ELSE scope_type
   END,
       scope_vertical_norm = NULL
 WHERE scope_type = 'vertical'
    OR scope_vertical_norm IS NOT NULL;

ALTER TABLE planner_semantic_projection_policy
  DROP INDEX uidx_semantic_projection_policy_scope,
  DROP INDEX idx_pspp_scope,
  DROP COLUMN scope_vertical_norm,
  ADD UNIQUE KEY uidx_semantic_projection_policy_scope (policy_key, scope_workspace_id),
  ADD KEY idx_pspp_scope (scope_workspace_id);

UPDATE planner_semantic_time_policy
   SET scope_type = CASE
       WHEN scope_type = 'vertical' THEN 'global'
       ELSE scope_type
   END,
       scope_vertical_norm = NULL
 WHERE scope_type = 'vertical'
    OR scope_vertical_norm IS NOT NULL;

ALTER TABLE planner_semantic_time_policy
  DROP INDEX uidx_semantic_time_policy_scope,
  DROP INDEX idx_pstp_scope,
  DROP COLUMN scope_vertical_norm,
  ADD UNIQUE KEY uidx_semantic_time_policy_scope (policy_key, scope_workspace_id),
  ADD KEY idx_pstp_scope (scope_workspace_id);
