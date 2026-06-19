# Embedding Engine And Vector Store Execution Ledger

## Purpose

Track implementation of the embedding runtime modularization work on branch
`feat/embedding-plugins`.

This workstream introduces two new plugin boundaries:

- embedding engines, which generate vectors from text
- vector stores, which persist vectors, cache reusable vectors, and serve
  similarity candidates

The branch also migrates the current SentenceTransformers/PyTorch runtime into
a first-party embedding engine plugin, adds a native ONNX Runtime embedding
engine, separates embedding storage from analyzer/index storage, and adds the
benchmark and provisioning surfaces needed to compare engines and models.

## Decisions

- Scope: implement the plugin contracts, migrate the current Torch runtime,
  add a native ONNX Runtime engine, add first-party vector-store plugins, and
  add benchmark/provisioning harnesses. Do not run the long campaign in this
  branch.
- Packaging: first-party embedding engines and vector stores are separate
  package distributions under `packages/`.
- Configuration:
  - `[embeddings] engine = "..."`
  - `[embeddings] vector_store = "..."`
  - engine options live under `[plugins.embedding-<name>]`
  - vector-store options live under `[plugins.vector-store-<name>]`
- Invalidation: persisted vector identity is engine-aware and vector-store
  format-aware. Existing vectors intentionally recompute once after the storage
  split.
- Coexistence: vector stores may retain multiple engine/model vector sets. The
  first implementation queries one active vector set at a time.
- ONNX: the first ONNX implementation is native ONNX Runtime, not the
  SentenceTransformers ONNX backend.
- Official bundle: include both first-party embedding engines and both
  first-party vector stores.
- Measurement: add scripts and smoke measurements only; the long model matrix is
  run later by the operator.
- Commit cadence: commit after each validated implementation step.

## Constraints

- No model weights or exported ONNX files are committed to git.
- Indexing remains explicit. No background service or daemon is introduced.
- Query-time retrieval reads persisted vectors only.
- Local model provisioning remains explicit and operator-controlled.
- Existing structural index backends remain responsible for symbols, docs,
  calls, references, ownership, and freshness.
- Vector stores own embedding rows, vector cache rows, pending embedding rows,
  and vector similarity.
- `codira index --full` may rebuild structural data without deleting reusable
  vector sets unless the active vector identity changes.
- A vector-store cleanup command or script must be explicit; stale vector sets
  are not silently dropped during ordinary indexing.
- Every behavior change must include focused tests and documentation.

## Model Campaign Set

The benchmark manifest must include:

- the current configured model
- `BAAI/bge-small-en-v1.5`
- `nomic-ai/nomic-embed-text-v1.5`
- `jinaai/jina-embeddings-v2-code-en`

The branch must provide commands and manifests for the campaign, but it must
only run fast smoke checks locally.

## Phase Ledger

- [x] Phase 0 - Execution ledger and ADR
- [x] Phase 1 - Core contracts for embedding engines and vector stores
- [x] Phase 2 - Registry and configuration selection
- [x] Phase 2b - Capability reporting
- [x] Phase 3a - SentenceTransformers engine package boundary
- [x] Phase 3b - SentenceTransformers runtime dispatcher migration
- [x] Phase 4a - Separated SQLite and DuckDB vector-store packages
- [ ] Phase 4b - Move backend embedding persistence to vector stores
- [x] Phase 5 - Native ONNX Runtime engine package
- [x] Phase 6 - Model manifests and provisioning scripts
- [x] Phase 7 - Bundle, user docs, developer docs, and ADR alignment
- [x] Phase 8 - Benchmark harness, smoke measurements, and campaign manifest
- [ ] Phase 9 - Full validation and merge handoff

## Phase Notes

### Phase 0

- Recorded the implementation decisions for the dedicated branch.
- Added ADR-022 for embedding engine and vector-store plugin boundaries.
- Added ADR-022 to the ADR index.

### Phase 1

- Added engine-neutral `EmbeddingEngineSpec`, `VectorStoreSpec`, and
  `VectorSetIdentity` identity dataclasses.
- Added runtime-checkable `EmbeddingEngine` and `VectorStore` protocols.
- Added engine-neutral `EmbeddingEngineError` and `VectorStoreError`.
- Extended the contract runtime-check test with fake embedding engine and vector
  store implementations.
- Focused validation passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_contracts.py::test_language_analyzer_index_backend_and_retrieval_protocols_are_runtime_checkable`.
- Targeted hooks passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pre-commit run --files src/codira/contracts.py tests/test_contracts.py`.

### Phase 2

- Added `[embeddings] engine` and `[embeddings] vector_store` selectors.
- Added default first-party plugin config tables for:
  - `plugins.embedding-sentence-transformers`
  - `plugins.embedding-onnx`
  - `plugins.vector-store-sqlite`
  - `plugins.vector-store-duckdb`
- Extended plugin table validation to accept `embedding-*` and
  `vector-store-*` namespaces.
- Extended registry discovery with `codira.embedding_engines` and
  `codira.vector_stores` entry-point groups.
- Extended plugin registration and configuration validation to include the new
  plugin families.
- Focused validation passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_config.py -k 'plugin_tables or full_profile or unknown_keys or embedding_indexing_origin' tests/test_plugins.py -k 'plugin'`.
- Targeted hooks passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pre-commit run --files src/codira/config.py src/codira/registry.py tests/test_config.py tests/test_plugins.py`.

### Phase 2b

- Added plugin-family metadata to `codira caps --json`.
- Extended the capability schema with deterministic plugin registration rows.
- Marked loaded analyzer plugins active, and marked the configured backend,
  embedding engine, and vector store active.
- Focused validation passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_capabilities.py`.
- Targeted hooks passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pre-commit run --files src/codira/capabilities.py src/codira/schema/capabilities.schema.json tests/test_capabilities.py`.
- CLI smoke passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run codira caps --json`.

### Phase 3a

- Added `packages/codira-embedding-sentence-transformers`.
- Published the `sentence-transformers` engine through the
  `codira.embedding_engines` entry-point group.
- Added package-local tests for entry-point metadata and factory shape.
- Added the package to root development metadata, the `semantic` extra, the
  official bundle extra, and `uv.lock`.
- Focused validation passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q packages/codira-embedding-sentence-transformers/tests/test_sentence_transformers_package.py`.
- Targeted hooks passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pre-commit run --files pyproject.toml uv.lock packages/codira-embedding-sentence-transformers/pyproject.toml packages/codira-embedding-sentence-transformers/README.md packages/codira-embedding-sentence-transformers/src/codira_embedding_sentence_transformers/__init__.py packages/codira-embedding-sentence-transformers/src/codira_embedding_sentence_transformers/py.typed packages/codira-embedding-sentence-transformers/tests/test_sentence_transformers_package.py`.

### Phase 3b

- Added registry helpers for active embedding engine and active vector-store
  singleton selection.
- Routed public embedding generation and provisioning through the configured
  embedding engine.
- Preserved the current SentenceTransformers implementation as an internal
  compatibility path used by the first-party engine package.
- Preserved existing test monkeypatch points around model loading and
  provisioning.
- Focused validation passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_embeddings.py -k 'embed_texts or load_model or sentence_transformer_factory' packages/codira-embedding-sentence-transformers/tests/test_sentence_transformers_package.py`.
- Targeted hooks passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pre-commit run --files src/codira/registry.py src/codira/semantic/embeddings.py packages/codira-embedding-sentence-transformers/src/codira_embedding_sentence_transformers/__init__.py`.

### Phase 4a

- Added `packages/codira-vector-store-sqlite`.
- Added `packages/codira-vector-store-duckdb`.
- Published `sqlite` and `duckdb` vector stores through the
  `codira.vector_stores` entry-point group.
- Added separated local vector-store files:
  - `.codira/embeddings.db`
  - `.codira/embeddings.duckdb`
- Added initial vector-store schemas for vector sets, vectors, vector cache, and
  pending vectors.
- Added package-local tests for metadata, factories, protocol compatibility, and
  schema initialization.
- Added the packages to root development metadata, the `semantic` extra, the
  official bundle extra, and `uv.lock`.
- Focused validation passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q packages/codira-vector-store-sqlite/tests/test_sqlite_vector_store_package.py packages/codira-vector-store-duckdb/tests/test_duckdb_vector_store_package.py`.
- Targeted hooks passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pre-commit run --files pyproject.toml uv.lock packages/codira-vector-store-sqlite/pyproject.toml packages/codira-vector-store-sqlite/README.md packages/codira-vector-store-sqlite/src/codira_vector_store_sqlite/__init__.py packages/codira-vector-store-sqlite/src/codira_vector_store_sqlite/py.typed packages/codira-vector-store-sqlite/tests/test_sqlite_vector_store_package.py packages/codira-vector-store-duckdb/pyproject.toml packages/codira-vector-store-duckdb/README.md packages/codira-vector-store-duckdb/src/codira_vector_store_duckdb/__init__.py packages/codira-vector-store-duckdb/src/codira_vector_store_duckdb/py.typed packages/codira-vector-store-duckdb/tests/test_duckdb_vector_store_package.py`.

### Phase 4b

- Initialized the configured vector store during normal indexing.
- Initialized the configured vector store during `codira index
  --embeddings-only`.
- Added regression coverage that deferred indexing creates the separated
  `.codira/embeddings.db` vector-store file independently from the structural
  index database.
- Remaining Phase 4b work: move pending/vector/cache row writes and query-time
  similarity reads out of structural backends and into vector-store plugins.
- Focused validation passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_incremental_indexing.py::test_index_cli_defers_and_processes_pending_embeddings`.
- Targeted hooks passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pre-commit run --files src/codira/indexer.py src/codira/cli.py tests/test_incremental_indexing.py`.

### Phase 5

- Added `packages/codira-embedding-onnx`.
- Published the `onnx` engine through the `codira.embedding_engines` entry-point
  group.
- Added local runtime configuration for:
  - `model_path`
  - `tokenizer_path`
  - `provider`
  - `precision`
  - `normalize`
  - `intra_op_num_threads`
  - `inter_op_num_threads`
- Implemented lazy ONNX Runtime and tokenizer loading so missing optional engine
  dependencies fail through `EmbeddingEngineError`.
- Added package-local tests for entry-point metadata, factory shape, and missing
  model configuration.
- Added the package to root development metadata, the `semantic` extra, the
  official bundle extra, and `uv.lock`.
- Bumped `codira-bundle-official` to `1.52.0` and aligned its dependency
  contract with the new official embedding/vector package set.
- Focused validation passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_contracts.py::test_root_optional_dependencies_support_monorepo_bundle_install packages/codira-bundle-official/tests/test_bundle_package.py packages/codira-embedding-onnx/tests/test_onnx_package.py`.
- Targeted hooks passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pre-commit run --files pyproject.toml uv.lock tests/test_contracts.py packages/codira-bundle-official/pyproject.toml packages/codira-bundle-official/tests/test_bundle_package.py packages/codira-embedding-onnx/pyproject.toml packages/codira-embedding-onnx/README.md packages/codira-embedding-onnx/src/codira_embedding_onnx/__init__.py packages/codira-embedding-onnx/src/codira_embedding_onnx/py.typed packages/codira-embedding-onnx/tests/test_onnx_package.py`.
- Full-suite validation note: `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`
  passed the previously failing bundle contract test, then was interrupted
  after `test_semgrep_rule_files_are_valid_yaml` waited several minutes on a
  semgrep subprocess.

### Phase 6

- Added `benchmarks/embedding-model-candidates.json`.
- Added `scripts/embedding_model_manifest.py` to validate/list manifest entries
  and render repository configuration snippets for selected engine/model
  entries.
- Covered the accepted campaign model set:
  - current `sentence-transformers/all-MiniLM-L6-v2`
  - `BAAI/bge-small-en-v1.5`
  - `nomic-ai/nomic-embed-text-v1.5`
  - `jinaai/jina-embeddings-v2-code-en`
- Included both `sentence-transformers` and `onnx` entries where local ONNX
  artifact paths are needed.
- Focused validation passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_embedding_model_manifest.py`.
- Targeted hooks passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pre-commit run --files benchmarks/embedding-model-candidates.json scripts/embedding_model_manifest.py tests/test_embedding_model_manifest.py`.
- Script smoke checks passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/embedding_model_manifest.py --list`.
- Config-render smoke passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/embedding_model_manifest.py --id bge-small-en-v1.5-onnx --print-config`.

### Phase 7

- Updated configuration docs with `embeddings.engine`,
  `embeddings.vector_store`, separated vector-store files, and the model
  candidate manifest.
- Updated getting-started docs to describe embedding engines and manifest
  config rendering.
- Updated script reference docs for `scripts/embedding_model_manifest.py` and
  active-engine provisioning.
- Updated plugin architecture docs with the embedding engine and vector-store
  plugin families and entry-point groups.
- Targeted hooks passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pre-commit run --files docs/configuration.md docs/getting_started.md docs/scripts.md docs/architecture/plugin-model.md`.

### Phase 8

- Added `benchmarks/embedding-engine-matrix.json` as the long matrix descriptor.
- Added `scripts/embedding_engine_matrix_plan.py` to build deterministic dry-run
  JSON plans from the matrix, model, and repository manifests.
- Added tests for matrix-plan construction and direct CLI JSON output.
- Documented the matrix-plan script.
- Focused validation passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_embedding_engine_matrix_plan.py`.
- Targeted hooks passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pre-commit run --files benchmarks/embedding-engine-matrix.json scripts/embedding_engine_matrix_plan.py tests/test_embedding_engine_matrix_plan.py`.
- Script smoke passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/embedding_engine_matrix_plan.py`.

### Phase 9

- Broad hooks passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pre-commit run --all-files`.
- Semgrep-excluded test suite passed:
  `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q --ignore=tests/test_semgrep_rules.py`
  with `394 passed`.
- Full-suite blocker: `test_semgrep_rule_files_are_valid_yaml` waits on a
  semgrep subprocess. A bounded repro timed out:
  `timeout 30s env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_semgrep_rules.py::test_semgrep_rule_files_are_valid_yaml`.
- Phase 9 remains open until the semgrep subprocess hang is resolved and the
  complete suite passes.
