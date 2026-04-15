-- Preflight audit queries. Run before the ALTER statements if you need to
-- inspect live rows before the scope collapse.
--
-- SELECT 'planner_domain_capability' AS table_name, scope_type, COUNT(*) AS row_count
--   FROM planner_domain_capability
--  GROUP BY scope_type
-- UNION ALL
-- SELECT 'planner_rerank_policy', scope_type, COUNT(*)
--   FROM planner_rerank_policy
--  GROUP BY scope_type
-- UNION ALL
-- SELECT 'planner_projection_policy', scope_type, COUNT(*)
--   FROM planner_projection_policy
--  GROUP BY scope_type
-- UNION ALL
-- SELECT 'planner_signal_policy', scope_type, COUNT(*)
--   FROM planner_signal_policy
--  GROUP BY scope_type
-- UNION ALL
-- SELECT 'planner_prompt_intent_policy', scope_type, COUNT(*)
--   FROM planner_prompt_intent_policy
--  GROUP BY scope_type
-- UNION ALL
-- SELECT 'planner_retrieval_policy', scope_type, COUNT(*)
--   FROM planner_retrieval_policy
--  GROUP BY scope_type
-- UNION ALL
-- SELECT 'planner_domain_selection_policy', scope_type, COUNT(*)
--   FROM planner_domain_selection_policy
--  GROUP BY scope_type;

UPDATE planner_domain_capability
   SET scope_type = CASE
       WHEN scope_type = 'vertical' THEN 'global'
       WHEN scope_type = 'vertical_domain' THEN 'global_domain'
       ELSE scope_type
   END,
       scope_vertical_norm = NULL
 WHERE scope_type IN ('vertical', 'vertical_domain')
    OR scope_vertical_norm IS NOT NULL;

ALTER TABLE planner_domain_capability
  DROP INDEX uidx_domain_capability_scope,
  DROP INDEX idx_pdc_scope,
  DROP COLUMN scope_vertical_norm,
  ADD UNIQUE KEY uidx_domain_capability_scope (
    base_domain_id,
    capability_key,
    scope_workspace_id,
    source_ref
  ),
  ADD KEY idx_pdc_scope (scope_workspace_id);

UPDATE planner_rerank_policy
   SET scope_type = CASE
       WHEN scope_type = 'vertical' THEN 'global'
       WHEN scope_type = 'vertical_domain' THEN 'global_domain'
       ELSE scope_type
   END,
       scope_vertical_norm = NULL
 WHERE scope_type IN ('vertical', 'vertical_domain')
    OR scope_vertical_norm IS NOT NULL;

ALTER TABLE planner_rerank_policy
  DROP INDEX uidx_rerank_policy_scope,
  DROP INDEX idx_prp_scope,
  DROP COLUMN scope_vertical_norm,
  ADD UNIQUE KEY uidx_rerank_policy_scope (
    policy_key,
    scope_workspace_id,
    scope_base_domain_id
  ),
  ADD KEY idx_prp_scope (scope_workspace_id, scope_base_domain_id);

UPDATE planner_projection_policy
   SET scope_type = CASE
       WHEN scope_type = 'vertical' THEN 'global'
       WHEN scope_type = 'vertical_domain' THEN 'global_domain'
       ELSE scope_type
   END,
       scope_vertical_norm = NULL
 WHERE scope_type IN ('vertical', 'vertical_domain')
    OR scope_vertical_norm IS NOT NULL;

ALTER TABLE planner_projection_policy
  DROP INDEX uidx_projection_policy_scope,
  DROP INDEX idx_ppp_scope,
  DROP COLUMN scope_vertical_norm,
  ADD UNIQUE KEY uidx_projection_policy_scope (
    policy_key,
    scope_workspace_id,
    scope_base_domain_id
  ),
  ADD KEY idx_ppp_scope (scope_workspace_id, scope_base_domain_id);

UPDATE planner_signal_policy
   SET scope_type = CASE
       WHEN scope_type = 'vertical' THEN 'global'
       ELSE scope_type
   END,
       scope_vertical_norm = NULL
 WHERE scope_type = 'vertical'
    OR scope_vertical_norm IS NOT NULL;

ALTER TABLE planner_signal_policy
  DROP INDEX uidx_signal_policy_scope,
  DROP INDEX idx_psp_scope,
  DROP COLUMN scope_vertical_norm,
  ADD UNIQUE KEY uidx_signal_policy_scope (policy_key, scope_workspace_id),
  ADD KEY idx_psp_scope (scope_workspace_id);

UPDATE planner_prompt_intent_policy
   SET scope_type = CASE
       WHEN scope_type = 'vertical' THEN 'global'
       ELSE scope_type
   END,
       scope_vertical_norm = NULL
 WHERE scope_type = 'vertical'
    OR scope_vertical_norm IS NOT NULL;

ALTER TABLE planner_prompt_intent_policy
  DROP INDEX uidx_prompt_intent_policy_scope,
  DROP INDEX idx_ppip_scope,
  DROP COLUMN scope_vertical_norm,
  ADD UNIQUE KEY uidx_prompt_intent_policy_scope (policy_key, scope_workspace_id),
  ADD KEY idx_ppip_scope (scope_workspace_id);

UPDATE planner_retrieval_policy
   SET scope_type = CASE
       WHEN scope_type = 'vertical' THEN 'global'
       ELSE scope_type
   END,
       scope_vertical_norm = NULL
 WHERE scope_type = 'vertical'
    OR scope_vertical_norm IS NOT NULL;

ALTER TABLE planner_retrieval_policy
  DROP INDEX uidx_retrieval_policy_scope,
  DROP INDEX idx_prp_scope,
  DROP COLUMN scope_vertical_norm,
  ADD UNIQUE KEY uidx_retrieval_policy_scope (policy_key, scope_workspace_id),
  ADD KEY idx_prp_scope (scope_workspace_id);

UPDATE planner_domain_selection_policy
   SET scope_type = CASE
       WHEN scope_type = 'vertical' THEN 'global'
       ELSE scope_type
   END,
       scope_vertical_norm = NULL
 WHERE scope_type = 'vertical'
    OR scope_vertical_norm IS NOT NULL;

ALTER TABLE planner_domain_selection_policy
  DROP INDEX uidx_domain_selection_policy_scope,
  DROP INDEX idx_pdsp_scope,
  DROP COLUMN scope_vertical_norm,
  ADD UNIQUE KEY uidx_domain_selection_policy_scope (policy_key, scope_workspace_id),
  ADD KEY idx_pdsp_scope (scope_workspace_id);
