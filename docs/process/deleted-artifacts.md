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

## Approved scripts and documentation cleanup — 2026-10-07

The operator approved the complete cleanup review. The pre-cleanup snapshot is
`f7d27c8b66777a5d0ec0b5bd231e4ddedb36ec42`. Unlike the older objects above, the objects in this
section are recovered from this snapshot:

```bash
git show 'f7d27c8b66777a5d0ec0b5bd231e4ddedb36ec42:<path>'
```

For binary assets redirect the `git show` output to a disposable file; do not
print image bytes to the terminal. Campaign specifications, generated manifests,
receipts, provider responses and measurement evidence were not removed or moved.

| Removed object | Reason / retained replacement |
| --- | --- |
| `scripts/run_agent_efficiency_phase0_live_probe.py` | Completed one-off paid probe; offline manifest/command/fixture/executable helpers and checks remain in `tests/test_agent_efficiency_phase0.py`. |
| `scripts/run_agent_efficiency_phase4_live_probe.py` | Completed, unreferenced one-off paid probe; current paid work uses the campaign factory. |
| `docs/process/agent-efficiency-campaign-011-launch-prompt.md` | Completed identity; retained initial results and correcting forensic audit. |
| `docs/badges/cartoon_cold.png` | Unused alternative badge. |
| `docs/badges/cartoon_warm.png` | Unused alternative badge. |
| `docs/badges/realistic.png` | Unused alternative badge. |
| `docs/badges/small.png` | Unused alternative badge. |
| `docs/favicon.ico` | Unused icon; MkDocs uses `favicon.png`. |
| `docs/images/IA_image.png` | Unreferenced image. |
| `docs/process/agent-efficiency-campaign-012-handoff-2026-10-04.md` | Superseded handoff; controls, failures, provenance and approval boundaries consolidated in the preparation history. |
| `docs/process/agent-efficiency-campaign-013-handoff-2026-10-04.md` | Superseded handoff; controls, failures, provenance and approval boundaries consolidated in the preparation history. |
| `docs/process/agent-efficiency-campaign-014-handoff-2026-10-04.md` | Superseded handoff; controls, failures, provenance and approval boundaries consolidated in the preparation history. |
| `docs/process/agent-efficiency-campaign-015-handoff-2026-10-04.md` | Superseded handoff; controls, failures, provenance and approval boundaries consolidated in the preparation history. |
| `docs/process/dual-campaign-017-018-preparation-2026-10-04.md` | Superseded handoff; controls, failures, provenance and approval boundaries consolidated in the preparation history. |
| `docs/process/luna-completion-024-2026-10-04.md` | Superseded handoff; controls, failures, provenance and approval boundaries consolidated in the preparation history. |

[Preparation history](agent-efficiency-preparation-history-2026-10-07.md) preserves
selected fingerprints, source/image bindings, financial controls and failure
chronology. Complete original prose and authorization wording remain in Git.

Five completed implementation ledgers and the calibration handoff retain their
original paths as concise closeouts with recovery commands. The architecture
squash-message correction and Qdrant live-server verification limitation remain
explicit. Campaign 010's prompt is marked historical without claiming it ran.
The dangling `ri_fix.py` documentation and Make target were removed; that script
was already absent from this snapshot. The retrieval evaluator, line inventory
and distribution export tools remain documented maintenance utilities.

Cleanup validation also exposed two calibration tests whose `--no-local` source
clone depended on the frozen fixture commit being reachable from the current
branch. Their test setup now exposes the unchanged retained Codira fixture
revision at a disposable source repository's detached HEAD. The production
launcher and frozen fixture definition are unchanged.
