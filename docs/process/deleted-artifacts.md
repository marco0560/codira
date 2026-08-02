# Removed Historical Objects

## Purpose

This index records repository material deliberately removed because it was a
closed implementation ledger, a dated audit, or an unmaintained one-off
experiment. It is retained by Git history, not by the working tree.

Each object below can be recovered with, for example:

```bash
git show c4ef4c51f304e1da6dd9c3e0c09958da0ba7391f:<path>
```

The referenced commit is the final commit containing every listed object.
Current development guidance lives in the maintained documentation, tests,
scripts, ADRs, roadmap, and GitHub issues.

## Closed Process Material

| Object | Description |
| --- | --- |
| `docs/process/assumption-audit-2026-04-24.md` | Dated assumption audit. |
| `docs/process/backend-agnostic-core-execution.md` | Completed backend-agnostic-core ledger. |
| `docs/process/duckdb-slowdown-fix-2026-06-25.md` | Dated DuckDB incident record. |
| `docs/process/embedding-engine-vector-store-execution.md` | Completed embedding/vector-store ledger. |
| `docs/process/embedding-performance-execution.md` | Completed embedding-performance ledger. |
| `docs/process/issue-001-real-embeddings-execution.md` | Closed issue #1 execution ledger. |
| `docs/process/issue-003-docs-retrieval-execution.md` | Closed issue #3 execution ledger. |
| `docs/process/issue-004-documentation-audit-plugins-execution.md` | Closed issue #4 execution ledger. |
| `docs/process/issue-009-capability-signal-layer-execution.md` | Closed issue #9 execution ledger. |
| `docs/process/issue-009-capability-signal-layer-inventory.md` | Superseded issue #9 inventory. |
| `docs/process/issue-010-call-graph-retrieval-producer-execution.md` | Closed issue #10 execution ledger. |
| `docs/process/issue-010-duckdb-backend.md` | Closed DuckDB implementation note. |
| `docs/process/issue-011-12-multirepo-v2-execution.md` | Completed multi-repository execution ledger. |
| `docs/process/issue-011-cpp-analyzer-execution-ledger.md` | Closed C++ analyzer ledger. |
| `docs/process/issue-017-configuration-system-execution.md` | Closed configuration-system ledger. |
| `docs/process/issue-021-c-constants-design-check.md` | Closed C constants design check. |
| `docs/process/issue-021-rich-symbol-modeling-execution.md` | Closed richer-symbol-modeling ledger. |
| `docs/process/issue-025-c-const-declarations-design.md` | Closed C declaration design note. |
| `docs/process/issue-027-plugin-configuration-injection-execution.md` | Closed plugin-configuration ledger. |
| `docs/process/issue-028-embedding-calibration-execution.md` | Closed embedding-calibration ledger. |
| `docs/process/issue-030-backend-performance-execution.md` | Closed backend-performance ledger. |
| `docs/process/issue-057-embedding-performance-execution.md` | Closed issue #57 execution ledger. |
| `docs/process/migration-plan-revised.md` | Completed repository migration plan. |
| `docs/process/retrieval-quality-benchmark-reminder-2026-07-07.md` | Dated benchmark reminder superseded by `docs/scripts.md`. |
| `docs/process/semantic-pipeline-optimization-plan.md` | Unstarted, superseded semantic optimization plan. |
| `docs/process/test-current-situation.md` | Dated test-state audit. |
| `docs/process/v2-0-0-migration-notes.md` | Completed v2 migration notes. |

## One-off Experimental Tooling

| Object | Description |
| --- | --- |
| `scripts/run_issue55_concurrency_campaign.sh` | Issue #55 workstation-specific concurrency campaign. |
| `scripts/run_issue57_embedding_matrix.py` | Issue #57 workstation-specific embedding matrix. |
| `scripts/compare_embedding_engines.py` | Compatibility helper used only by removed split-engine experiment. |
| `scripts/run_split_embedding_engine_experiment.py` | Non-production split embedding-engine experiment. |
| `scripts/run_onnx_parameter_sweep.py` | Superseded ONNX parameter sweep. |
| `scripts/embedding_engine_matrix_plan.py` | Dry-run planner for the removed historical matrix. |
| `benchmarks/split-embedding-engine-pairs.json` | Manifest for the removed split-engine experiment. |
| `benchmarks/onnx-parameter-sweep.json` | Manifest for the removed ONNX sweep. |
| `benchmarks/embedding-engine-matrix.json` | Manifest for the removed historical matrix. |
| `tests/test_compare_embedding_engines.py` | Tests dedicated to removed compatibility helper. |
| `tests/test_split_embedding_engine_experiment.py` | Tests dedicated to removed split-engine experiment. |
| `tests/test_onnx_parameter_sweep.py` | Tests dedicated to removed ONNX sweep. |
| `tests/test_embedding_engine_matrix_plan.py` | Tests dedicated to removed matrix planner. |
