# Issue #57 Embedding Performance Execution Ledger

## Purpose

Track implementation of issue `#57` on branch
`feat/issue-57-embedding-optimization` as one phased embedding-performance
workstream.

This ledger records:

- benchmark-harness prerequisites
- embedding configuration and CLI contract changes
- embedding volume controls
- persistent vector-cache backend changes
- deferred and resumable embedding execution
- documentation, versioning, validation, and benchmark evidence

## Branch

```text
feat/issue-57-embedding-optimization
```

## Constraints

- At least one commit must be created at the end of every completed phase.
- Each phase commit must remain scoped to that phase.
- Existing embedding defaults must preserve current behavior unless operators
  explicitly opt in to reduced volume or deferred indexing.
- `embeddings.enabled = false` remains a hard disable.
- Backend schema changes use the current-schema-only policy.
- Warm embedding service implementation is deferred until query-startup
  measurements justify it.
- Finish with `uv run pre-commit run --all-files`, `uv run pytest -q`,
  `uv run codira index`, and `uv run codira audit`.

## Phase Ledger

- [x] Phase 0 - Benchmark harness prerequisite and execution ledger
- [x] Phase 1 - Config and CLI contract
- [ ] Phase 2 - Metrics and embedding volume controls
- [ ] Phase 3 - Persistent vector cache
- [ ] Phase 4 - Deferred and resumable embeddings
- [ ] Phase 5 - Documentation, versioning, validation, and benchmark evidence

## Phase Notes

### Phase 0

- Created this execution ledger before embedding behavior changes.
- Recorded the existing Hyperfine compatibility fix as issue `#57`
  prerequisite work.
- Removed the incompatible `--show-output` flag from campaign Hyperfine
  command construction while keeping `--style full` and `--ignore-failure`.
- Updated benchmark-campaign tests so generated Hyperfine argv must not include
  `--show-output`.
- Targeted validation passed:
  `uv run pytest -q tests/test_bootstrap_scripts.py -k benchmark_campaign`.
- `uv run pre-commit run --all-files` passed after the harness fix.

### Phase 1

- Added the `embeddings.indexing` config table with:
  - `mode = "immediate"`
  - `object_types = ["symbol", "documentation"]`
  - `max_text_chars = 0`
  - `include_paths = []`
  - `exclude_paths = []`
- Added strict validation for embedding indexing mode, object types, duplicate
  object types, text-size limits, and path-filter list values.
- Added `codira index --defer-embeddings` and `codira index --embeddings-only`
  parser support.
- Preserved current default behavior by keeping immediate embedding computation
  as the effective default.
- Added explicit hard-gate validation so embedding execution flags cannot
  override `embeddings.enabled = false`.
- Added JSON and text index report fields for skipped, pending, mode, and
  completion status.
- Targeted validation passed:
  `uv run pytest -q tests/test_config.py tests/test_incremental_indexing.py -k 'config or json_for_index_summary or required_coverage_failure or unsupported_deferred_embedding_mode or embedding_mode_flags or initializes_backend_before_indexing'`.
- `uv run pytest -q` passed with the Phase 1 contract changes.
- `uv run pre-commit run --all-files` passed after the contract changes.
