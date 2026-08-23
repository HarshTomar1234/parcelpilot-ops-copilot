# Agent Trajectory Evaluation

This run used `anthropic/claude-haiku-4-5-20251001` as both agent LLM and judge - task completion below is a real LLM-judged score.

## Method

19 golden cases with a real question and a non-empty expected_tools list. For each: run the actual agent (app/agent/orchestrator.py::run_agent) against the real database with the case's own role/account_scope, then score tool correctness (DeepEval's ToolCorrectnessMetric, exact match, no judge needed) and terminal-status match against the case's expected_status.

## Results

- Provider: `anthropic` / model `claude-haiku-4-5-20251001`
- Judge: `anthropic/claude-haiku-4-5-20251001`
- Cases evaluated: **19**
- Mean tool correctness: **0.84**
- Status match rate: **0.94** (17 status-checkable cases; the rest expect an action_pending/action_completed/rejected status, out of scope for Phase 3)
- Task completion: scored for 17 of 19 cases (harness-blocked for the rest: `'actual_output' cannot be empty for the 'Task Completion' metric`)
- Mean task completion (real LLM-judged score, scored cases only): **0.55**

## Per-case results

| Case | Tools expected | Tools called | Tool correctness | Status expected | Status actual | Match | Task completion |
|---|---|---|---|---|---|---|---|
| GC-001 | lookup_structured_data, search_documents, calculate_support_outcome | lookup_structured_data, calculate_support_outcome, search_documents | 1.00 | completed | completed | yes | 0.95 |
| GC-002 | search_documents |  | 0.00 | needs_clarification | needs_clarification | yes | - |
| GC-003 | lookup_structured_data, search_documents | lookup_structured_data, calculate_support_outcome, search_documents | 1.00 | completed | completed | yes | 0.90 |
| GC-004 | lookup_structured_data, search_documents, calculate_support_outcome | lookup_structured_data, calculate_support_outcome, search_documents | 1.00 | completed | completed | yes | 0.95 |
| GC-005 | lookup_structured_data, search_documents, calculate_support_outcome | lookup_structured_data, search_documents | 0.67 | completed | completed | yes | 0.35 |
| GC-006 | lookup_structured_data, search_documents | lookup_structured_data, calculate_support_outcome, search_documents | 1.00 | completed | completed | yes | 0.00 |
| GC-007 | lookup_structured_data, search_documents, calculate_support_outcome | lookup_structured_data, calculate_support_outcome, search_documents | 1.00 | completed | completed | yes | 0.95 |
| GC-008 | lookup_structured_data, search_documents, calculate_support_outcome | lookup_structured_data, calculate_support_outcome, search_documents | 1.00 | completed | completed | yes | 1.00 |
| GC-009 | lookup_structured_data, search_documents, calculate_support_outcome | lookup_structured_data, search_documents, calculate_support_outcome | 1.00 | completed | completed | yes | 0.95 |
| GC-010 | lookup_structured_data, search_documents, calculate_support_outcome | lookup_structured_data, calculate_support_outcome, search_documents | 1.00 | completed | completed | yes | 0.60 |
| GC-011 | lookup_structured_data, search_documents | lookup_structured_data, search_documents | 1.00 | completed | completed | yes | 0.35 |
| GC-012 | lookup_structured_data, search_documents | lookup_structured_data, search_documents | 1.00 | completed | completed | yes | 0.35 |
| GC-013 | search_documents | search_documents | 1.00 | completed | completed | yes | 0.35 |
| GC-014 | lookup_structured_data, search_documents | lookup_structured_data, search_documents | 1.00 | completed | completed | yes | 0.15 |
| GC-015 | lookup_structured_data, search_documents | lookup_structured_data, search_documents | 1.00 | insufficient_evidence | insufficient_evidence | yes | - |
| GC-016 | lookup_structured_data, search_documents | search_documents | 0.50 | insufficient_evidence | completed | NO | 0.00 |
| GC-022 | lookup_structured_data, search_documents, calculate_support_outcome, prepare_action | lookup_structured_data, calculate_support_outcome, search_documents | 0.75 | None | completed | - | 0.75 |
| GC-027 | lookup_structured_data, search_documents, calculate_support_outcome, prepare_action | lookup_structured_data, calculate_support_outcome, search_documents | 0.75 | None | completed | - | 0.75 |
| GC-028 | lookup_structured_data, search_documents, calculate_support_outcome | search_documents | 0.33 | completed | completed | yes | 0.00 |
