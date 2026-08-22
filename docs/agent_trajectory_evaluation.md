# Agent Trajectory Evaluation

**This run used MockProvider.** Tool correctness and status-match below are genuine, non-fabricated scores - they compare the real agent's actual tool calls and terminal status against the golden dataset, and need no LLM judge. Task completion (an LLM-judged metric) could not be scored with MockProvider as the judge - see the harness-blocked note below; this mirrors docs/deepeval_baseline.md's documented limitation, not a new one.

## Method

19 golden cases with a real question and a non-empty expected_tools list. For each: run the actual agent (app/agent/orchestrator.py::run_agent) against the real database with the case's own role/account_scope, then score tool correctness (DeepEval's ToolCorrectnessMetric, exact match, no judge needed) and terminal-status match against the case's expected_status.

## Results

- Provider: `mock` / model `mock-model`
- Judge: `mock/mock-model`
- Cases evaluated: **19**
- Mean tool correctness: **0.84**
- Status match rate: **0.88** (17 status-checkable cases; the rest expect an action_pending/action_completed/rejected status, out of scope for Phase 3)
- Task completion: scored for 0 of 19 cases (harness-blocked for the rest: `Evaluation LLM outputted an invalid JSON. Please use a better evaluation model.`)

## Per-case results

| Case | Tools expected | Tools called | Tool correctness | Status expected | Status actual | Match |
|---|---|---|---|---|---|---|
| GC-001 | lookup_structured_data, search_documents, calculate_support_outcome | lookup_structured_data, calculate_support_outcome, search_documents | 1.00 | completed | completed | yes |
| GC-002 | search_documents |  | 0.00 | needs_clarification | needs_clarification | yes |
| GC-003 | lookup_structured_data, search_documents | lookup_structured_data, calculate_support_outcome, search_documents | 1.00 | completed | completed | yes |
| GC-004 | lookup_structured_data, search_documents, calculate_support_outcome | lookup_structured_data, calculate_support_outcome, search_documents | 1.00 | completed | completed | yes |
| GC-005 | lookup_structured_data, search_documents, calculate_support_outcome | lookup_structured_data, search_documents | 0.67 | completed | completed | yes |
| GC-006 | lookup_structured_data, search_documents | lookup_structured_data, calculate_support_outcome, search_documents | 1.00 | completed | completed | yes |
| GC-007 | lookup_structured_data, search_documents, calculate_support_outcome | lookup_structured_data, calculate_support_outcome, search_documents | 1.00 | completed | completed | yes |
| GC-008 | lookup_structured_data, search_documents, calculate_support_outcome | lookup_structured_data, calculate_support_outcome, search_documents | 1.00 | completed | completed | yes |
| GC-009 | lookup_structured_data, search_documents, calculate_support_outcome | lookup_structured_data, search_documents, calculate_support_outcome | 1.00 | completed | completed | yes |
| GC-010 | lookup_structured_data, search_documents, calculate_support_outcome | lookup_structured_data, calculate_support_outcome, search_documents | 1.00 | completed | completed | yes |
| GC-011 | lookup_structured_data, search_documents | lookup_structured_data, search_documents | 1.00 | completed | completed | yes |
| GC-012 | lookup_structured_data, search_documents | lookup_structured_data, search_documents | 1.00 | completed | completed | yes |
| GC-013 | search_documents | search_documents | 1.00 | completed | completed | yes |
| GC-014 | lookup_structured_data, search_documents | lookup_structured_data, search_documents | 1.00 | completed | completed | yes |
| GC-015 | lookup_structured_data, search_documents | lookup_structured_data, search_documents | 1.00 | insufficient_evidence | completed | NO |
| GC-016 | lookup_structured_data, search_documents | search_documents | 0.50 | insufficient_evidence | completed | NO |
| GC-022 | lookup_structured_data, search_documents, calculate_support_outcome, prepare_action | lookup_structured_data, calculate_support_outcome, search_documents | 0.75 | None | completed | - |
| GC-027 | lookup_structured_data, search_documents, calculate_support_outcome, prepare_action | lookup_structured_data, calculate_support_outcome, search_documents | 0.75 | None | completed | - |
| GC-028 | lookup_structured_data, search_documents, calculate_support_outcome | search_documents | 0.33 | completed | completed | yes |
