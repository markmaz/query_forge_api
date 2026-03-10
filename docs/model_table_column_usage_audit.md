# model_table/model_column Usage Audit

Generated: 2026-03-09 23:24:53 CDT

## Summary
- Files with any reference (model_table/model_column/model_table_id/model_column_id): 93
- App files with any reference: 58
- Test files with any reference: 33
- Script/util files with any reference: 5
- App files with direct SQL use of model_table/model_column: 36

## Any Reference (App)
app/infra/qdrant_client.py
app/models/model_column_semantic.py
app/models/semantic_registry.py
app/models/semantic_suggestion.py
app/routes/ai.py
app/routes/domain_routes.py
app/routes/embeddings.py
app/routes/model_routes.py
app/routes/semantic_concepts.py
app/routes/semantic_mappings.py
app/scripts/backfill_model_column_semantics.py
app/scripts/backfill_semantic_types.py
app/services/admin/domain_profile_builder.py
app/services/ai_suggest_service.py
app/services/analytics/dictionary_enrichment_service.py
app/services/analytics/model_catalog_writer.py
app/services/analytics/profiling_service.py
app/services/domain/builder_column_feed_service.py
app/services/domain/domain_admin_write_service.py
app/services/domain/domain_column_sample_read_service.py
app/services/domain/domain_join_service.py
app/services/domain/domain_table_read_service.py
app/services/domain/domain_table_write_service.py
app/services/domain/domain_user_read_service.py
app/services/domain/user_domain_read_service.py
app/services/domain_resolver.py
app/services/domains/capabilities_service.py
app/services/domains/domain_resolver_service.py
app/services/embedding/embedding_index_service.py
app/services/embedding/embedding_search_service.py
app/services/models/model_column_search_service.py
app/services/models/model_read_service.py
app/services/models/model_sample_read_service.py
app/services/models/model_sample_write_service.py
app/services/models/model_snapshot_import_service.py
app/services/models/model_update_service.py
app/services/models/model_upload_service.py
app/services/models/model_write_service.py
app/services/nlp/dictionary_ner.py
app/services/planner_domain/map_to_sqljson.py
app/services/planner_domain/service.py
app/services/planner_llm/service.py
app/services/query_forge_service.py
app/services/query_studio/domain_explorer_service.py
app/services/recon/workspace_recon_service.py
app/services/semantic/concept_to_column_service.py
app/services/semantic/constrained_column_vector_service.py
app/services/semantic/domain_selection_service.py
app/services/semantic/plan_service.py
app/services/semantic/semantic_assignment_service.py
app/services/semantic/semantic_card_service.py
app/services/semantic/semantic_concept_service.py
app/services/semantic/semantic_mapping_service.py
app/services/semantic/semantic_suggestion_service.py
app/services/workspace_inventory/unmapped_workspace_tables_read_service.py
app/services/workspace_inventory/workspace_sample_write_service.py
app/services/workspace_inventory/workspace_snapshot_service.py
app/utils/sync_dictionary_from_dbx_ai.py

## Any Reference (Routes)
app/routes/ai.py
app/routes/domain_routes.py
app/routes/embeddings.py
app/routes/model_routes.py
app/routes/semantic_concepts.py
app/routes/semantic_mappings.py

## Any Reference (Services)
app/services/admin/domain_profile_builder.py
app/services/ai_suggest_service.py
app/services/analytics/dictionary_enrichment_service.py
app/services/analytics/model_catalog_writer.py
app/services/analytics/profiling_service.py
app/services/domain/builder_column_feed_service.py
app/services/domain/domain_admin_write_service.py
app/services/domain/domain_column_sample_read_service.py
app/services/domain/domain_join_service.py
app/services/domain/domain_table_read_service.py
app/services/domain/domain_table_write_service.py
app/services/domain/domain_user_read_service.py
app/services/domain/user_domain_read_service.py
app/services/domain_resolver.py
app/services/domains/capabilities_service.py
app/services/domains/domain_resolver_service.py
app/services/embedding/embedding_index_service.py
app/services/embedding/embedding_search_service.py
app/services/models/model_column_search_service.py
app/services/models/model_read_service.py
app/services/models/model_sample_read_service.py
app/services/models/model_sample_write_service.py
app/services/models/model_snapshot_import_service.py
app/services/models/model_update_service.py
app/services/models/model_upload_service.py
app/services/models/model_write_service.py
app/services/nlp/dictionary_ner.py
app/services/planner_domain/map_to_sqljson.py
app/services/planner_domain/service.py
app/services/planner_llm/service.py
app/services/query_forge_service.py
app/services/query_studio/domain_explorer_service.py
app/services/recon/workspace_recon_service.py
app/services/semantic/concept_to_column_service.py
app/services/semantic/constrained_column_vector_service.py
app/services/semantic/domain_selection_service.py
app/services/semantic/plan_service.py
app/services/semantic/semantic_assignment_service.py
app/services/semantic/semantic_card_service.py
app/services/semantic/semantic_concept_service.py
app/services/semantic/semantic_mapping_service.py
app/services/semantic/semantic_suggestion_service.py
app/services/workspace_inventory/unmapped_workspace_tables_read_service.py
app/services/workspace_inventory/workspace_sample_write_service.py
app/services/workspace_inventory/workspace_snapshot_service.py

## Any Reference (Models)
app/models/model_column_semantic.py
app/models/semantic_registry.py
app/models/semantic_suggestion.py

## Any Reference (Scripts/Utils)
app/scripts/backfill_model_column_semantics.py
app/scripts/backfill_semantic_types.py
app/utils/sync_dictionary_from_dbx_ai.py
scripts/backfill_primary_semantic_keys.py
scripts/debug_plan.py

## Any Reference (Tests)
tests/analytics/test_dictionary_enrichment_service.py
tests/routes/test_semantic_concepts_routes.py
tests/routes/test_semantic_routes.py
tests/semantic/test_semantic_canonical_mapping.py
tests/semantic/test_semantic_postprocess.py
tests/services/admin/test_domain_profile_builder.py
tests/services/embedding/test_embedding_search_service_semantic.py
tests/services/models/test_model_sample_read_service.py
tests/services/models/test_model_sample_write_service.py
tests/services/models/test_model_snapshot_import_service.py
tests/services/models/test_model_write_service.py
tests/services/planner/test_unified_llm_planner.py
tests/services/planner_domain/test_conversation_context.py
tests/services/planner_domain/test_map_to_sqljson.py
tests/services/planner_domain/test_service.py
tests/services/planner_domain/test_validate_v2.py
tests/services/planner_llm/test_golden_ratio.py
tests/services/semantic/test_concept_to_column_service.py
tests/services/semantic/test_constrained_column_vector_service.py
tests/services/semantic/test_domain_selection_service.py
tests/services/semantic/test_plan_service.py
tests/services/semantic/test_semantic_concept_service.py
tests/services/semantic/test_semantic_mapping_service.py
tests/services/semantic/test_semantic_suggestion_service.py
tests/services/semantic/test_slot_driven_planner.py
tests/services/test_domain_admin_write_service.py
tests/services/test_domain_column_sample_read_service.py
tests/services/test_domain_join_service.py
tests/services/test_domain_table_read_service.py
tests/services/test_domain_table_write_service.py
tests/services/test_query_forge_service_compile_extra.py
tests/services/test_sqljson_apply_service.py
tests/test_column_embedding.py

## Direct SQL Touchpoints (App)
app/routes/model_routes.py
app/scripts/backfill_model_column_semantics.py
app/scripts/backfill_semantic_types.py
app/services/admin/domain_profile_builder.py
app/services/analytics/dictionary_enrichment_service.py
app/services/analytics/model_catalog_writer.py
app/services/analytics/profiling_service.py
app/services/domain/builder_column_feed_service.py
app/services/domain/domain_admin_write_service.py
app/services/domain/domain_column_sample_read_service.py
app/services/domain/domain_join_service.py
app/services/domain/domain_table_read_service.py
app/services/domain/domain_table_write_service.py
app/services/domain/domain_user_read_service.py
app/services/domain/user_domain_read_service.py
app/services/domains/capabilities_service.py
app/services/domains/domain_resolver_service.py
app/services/embedding/embedding_index_service.py
app/services/models/model_column_search_service.py
app/services/models/model_read_service.py
app/services/models/model_sample_read_service.py
app/services/models/model_sample_write_service.py
app/services/models/model_snapshot_import_service.py
app/services/models/model_update_service.py
app/services/models/model_write_service.py
app/services/nlp/dictionary_ner.py
app/services/planner_llm/service.py
app/services/query_forge_service.py
app/services/query_studio/domain_explorer_service.py
app/services/recon/workspace_recon_service.py
app/services/semantic/concept_to_column_service.py
app/services/semantic/semantic_assignment_service.py
app/services/semantic/semantic_card_service.py
app/services/semantic/semantic_concept_service.py
app/services/workspace_inventory/workspace_snapshot_service.py
app/utils/sync_dictionary_from_dbx_ai.py
