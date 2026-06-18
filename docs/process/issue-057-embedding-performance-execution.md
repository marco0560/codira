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
- [x] Phase 2 - Metrics and embedding volume controls
- [x] Phase 3 - Persistent vector cache
- [x] Phase 4 - Deferred and resumable embeddings
- [x] Phase 5 - Documentation, versioning, validation, and benchmark evidence

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

### Phase 2

- Added the backend-neutral `EmbeddingIndexingPolicy` contract for:
  - object-type filtering
  - maximum text length filtering
  - include path filtering
  - exclude path filtering
- Added mutable `EmbeddingIndexingMetrics` so backends can report skipped
  embedding candidates without changing the public `(recomputed, reused)`
  persistence return contract.
- Threaded the effective `embeddings.indexing` config through the indexer into
  SQLite and DuckDB persistence requests.
- Filtered pending embedding rows in both SQLite and DuckDB immediately before
  embedding flushes, leaving structural rows and relationships unchanged.
- Added an end-to-end index JSON regression for configured object-type
  filtering and skipped-row reporting.
- Targeted validation passed:
  `uv run pytest -q tests/test_incremental_indexing.py -k 'embedding_rows_skipped_by_volume_controls or json_for_index_summary'`.
- Backend embedding validation passed:
  `uv run pytest -q tests/test_embeddings.py packages/codira-backend-sqlite/tests/test_sqlite_backend_package.py packages/codira-backend-duckdb/tests/test_duckdb_backend_package.py -k 'embedding'`.
- `uv run pytest -q` passed with the Phase 2 volume controls.
- `uv run pre-commit run --all-files` passed after the Phase 2 changes.

### Phase 3

- Added schema version `20` with a backend-neutral
  `embedding_vector_cache` table keyed by backend, version, dimension, and
  content hash.
- Added SQLite and DuckDB persistent vector-cache lookups before embedding
  inference.
- Stored newly encoded vectors in the cache during embedding flushes.
- Counted cache hits as reused embeddings while preserving the public backend
  persistence return contract.
- Added a low-level SQLite regression that prepopulates the cache and verifies
  inference is not invoked for a matching content hash.
- Updated plugin schema-version expectations for the first-party backends.
- Targeted validation passed:
  `uv run pytest -q tests/test_embeddings.py -k 'flush_embedding_rows'`.
- DuckDB embedding validation passed:
  `uv run pytest -q packages/codira-backend-duckdb/tests/test_duckdb_backend_package.py -k embedding`.
- `uv run pytest -q` passed with the Phase 3 cache changes.
- `uv run pre-commit run --all-files` passed after the Phase 3 changes.

### Phase 4

- Added schema version `21` with a `pending_embeddings` table for deferred
  embedding rows.
- Replaced the temporary deferred-mode CLI rejection with execution behavior:
  - `codira index --defer-embeddings` indexes structural data and queues
    eligible embedding rows.
  - `codira index --embeddings-only` drains pending rows without reparsing
    source files.
- Added backend contract support for deferred queueing and pending-row
  processing.
- Implemented pending-row queue/drain behavior in SQLite and DuckDB.
- Added pending-row cleanup when materialized embeddings are written or file
  owned rows are deleted.
- Updated fake and memory test backends to satisfy the expanded backend
  protocol.
- Added an end-to-end CLI regression for deferring and then processing pending
  embeddings.
- Targeted validation passed:
  `uv run pytest -q tests/test_incremental_indexing.py -k 'defers_and_processes_pending_embeddings or embedding_rows_skipped_by_volume_controls or embedding_mode_flags'`.
- Protocol validation passed:
  `uv run pytest -q tests/test_contracts.py::test_language_analyzer_index_backend_and_retrieval_protocols_are_runtime_checkable tests/test_memory_backend.py::test_memory_backend_implements_full_contract_without_sql_dependency tests/test_memory_backend.py::test_registry_can_select_memory_backend_entry_point`.
- `uv run pytest -q` passed with the Phase 4 deferred embedding changes.
- `uv run pre-commit run --all-files` passed after the Phase 4 changes.

### Phase 5

- Documented the embedding indexing controls in `docs/configuration.md`,
  including immediate versus deferred mode, object-type filtering, text-size
  filtering, and path-prefix filters.
- Updated `README.md` with the default symbol and documentation embedding
  behavior plus the two-step deferred indexing workflow.
- Updated architecture documentation for:
  - pending embedding rows
  - persistent vector caching by backend, version, dimension, and content hash
  - backend responsibilities for deferred embedding queueing and draining
- Bumped the touched backend package versions to `1.45.0`.
- Bumped `codira-bundle-official` to `1.47.0` and refreshed first-party backend
  pins in the bundle and root optional dependencies.
- Refreshed `uv.lock` after the package-version changes.
- Focused validation passed:
  `uv run pytest -q tests/test_incremental_indexing.py -k 'defers_and_processes_pending_embeddings or embedding_rows_skipped_by_volume_controls'`.
- Config and plugin validation passed:
  `uv run pytest -q tests/test_config.py tests/test_plugins.py -k 'embedding_indexing or backend_plugins_cli'`.
- Full validation passed:
  `uv run pytest -q`.
- Repository validation passed:
  `uv run pre-commit run --all-files`.
- Codira self-checks passed:
  `uv run codira index`, `uv run codira audit`, `uv run codira index -h`,
  and `uv run codira caps --json`.

### Phase 6

- Replaced DuckDB row-wise embedding queue and vector-cache writes with chunked
  Arrow replacement-scan batches.
- Added typed `BackendError` diagnostics for DuckDB embedding batch failures,
  including operation, row count, and approximate payload size.
- Added regression tests for:
  - avoiding `executemany()` in DuckDB embedding queue/cache helpers
  - chunked cached-vector persistence
  - batch failure diagnostics
- Bumped `codira-backend-duckdb` to `1.46.0`.
- Bumped `codira-bundle-official` to `1.48.0` and refreshed the DuckDB backend
  pin in the bundle and root optional dependencies.
- Validation passed:
  - `uv run pytest -q packages/codira-backend-duckdb/tests/test_duckdb_backend_package.py packages/codira-bundle-official/tests/test_bundle_package.py tests/test_contracts.py::test_root_optional_dependencies_support_monorepo_bundle_install`
  - `uv run python scripts/validate_repo.py`
  - `uv run pre-commit run --all-files`
  - `uv run pytest -q`
  - `.venv/bin/codira index`
  - `.venv/bin/codira audit --json`
  - `.venv/bin/codira caps --json`
- DuckDB full-index smoke checks passed without vector-cache OOM or batch
  failures:
  - small: Codira repository, 4,004 embeddings recomputed
  - medium: Redis, 12,528 embeddings recomputed
  - large: Postgres, 33,539 embeddings recomputed

### Phase 7

- Analyzed the completed Issue #57 embedding matrix, including the
  power-outage-interrupted first part, the resumed finishing DuckDB campaign,
  and the previous SQLite/DuckDB bk-cpp baseline.
- Recorded the final analysis under
  `.artifacts/analysis/2026-06-18-issue-057-embedding-matrix-analysis.md`.
- Kept the repository performance profile on DuckDB with immediate symbol and
  documentation embeddings enabled.
- Removed the local documentation text cap from the committed repo config
  because the matrix showed capped documentation embeddings do not materially
  reduce total runtime.
- Fixed the DuckDB deferred full-index write path by buffering session-level
  deferred pending rows and flushing them only after structural full-index rows
  have committed.
- Documented that the embedding matrix should be re-run after meaningful
  hardware changes because it is hardware-sensitive and long-running.
