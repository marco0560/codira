# Issue 003 Documentation Retrieval Channel Execution

This ledger tracks implementation of issue #3: adding a first-class
documentation retrieval channel to `ctx`.

## Scope

In scope:

- Add documentation artifacts as a backend-neutral analyzer output.
- Index all non-excluded Markdown files as deterministic heading sections.
- Index Python module docstrings as module-level documentation artifacts.
- Persist and query documentation artifacts consistently in SQLite, DuckDB, and
  the in-memory contract backend.
- Retrieve documentation through a distinct `docs` channel in `ctx`.
- Use dedicated documentation embeddings instead of mixing documentation text
  into the symbol embedding pool.
- Expose documentation provenance in JSON and explain output.

Out of scope for V1:

- Function, class, and method docstring retrieval.
- Arbitrary comment-block harvesting.
- Generic C/C++ block comments.
- Rustdoc, Doxygen, reStructuredText, or other non-Markdown documentation
  formats.
- A docs-only CLI command.

## Phase Ledger

| Phase | Status | Evidence | Commit |
|-------|--------|----------|--------|
| 0. Scope and execution ledger | Complete | Ledger created. | `217e8d4` |
| 1. Models and analyzer contract | Complete | Added `DocumentationArtifact`, documentation literals, and shared row aliases. `uv run ruff check src/codira/models.py src/codira/types.py`; `uv run ruff format --check src/codira/models.py src/codira/types.py`. | `562b9cd` |
| 2. Source extraction | Complete | Markdown analyzer, Python module-doc artifacts, analyzer capability wiring, first-party package wiring, and symbol-index skip guard for documentation-only analyses. Focused analyzer/plugin/package tests and Ruff checks passed. | `a89dfc0` |
| 3. Backend persistence and embeddings | Complete | SQLite, DuckDB, and in-memory backends persist/query docs and doc embeddings through a distinct documentation object type. Focused backend tests and Ruff checks passed. | Pending |
| 4. `ctx` retrieval and output | Pending | `docs` channel, result union, intent weighting, provenance, and explain output. | Pending |
| 5. Validation and cleanup | Pending | Full validation and ledger closure. | Pending |

## Decisions

- Documentation results participate in unified `top_matches` as typed results.
- Documentation storage is dedicated and distinct from symbol storage.
- Markdown stable IDs use source kind, repo-relative path, normalized heading
  path, and deterministic ordinal.
- Markdown segmentation is heading-based; front matter is ignored, and fenced
  code blocks stay inside their owning section.
- Documentation retrieval is intent-weighted: strong for architecture,
  navigation, process, setup, release, configuration, API contract, and
  rationale queries; conservative for runtime behavior, debugging, bug fixing,
  and tests.
- Backend parity is mandatory for SQLite, DuckDB, and the in-memory backend.

## Phase Notes

### Phase 0

- Created this ledger before behavior changes.
- Worktree was clean before the ledger was added.

### Phase 1

- Added the backend-neutral documentation artifact model.
- Extended `AnalysisResult` with ordered documentation artifacts while keeping
  the default empty for existing analyzer outputs.
- Added shared documentation row aliases for later backend and query work.

### Phase 2

- Added a first-party Markdown analyzer package that emits deterministic
  section/file documentation artifacts without pretending Markdown is a symbol
  language.
- Added Python module docstring documentation artifacts while leaving callable
  docstrings out of scope.
- Declared the `documentation` ontology capability across analyzer contracts
  and marked non-documenting analyzers as not supporting it.
- Wired Markdown into first-party package inventory, bundle metadata, split-repo
  scripts, bootstrap expectations, and compatibility shims.
- Added backend guards so documentation-only analyses can preserve file
  ownership without creating code symbols or reference-scan rows.
- Validation:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q packages/codira-analyzer-markdown/tests/test_markdown_package.py packages/codira-analyzer-python/tests/test_python_package.py tests/test_capabilities.py tests/test_plugins.py -k "markdown or python_analyzer_declares or capability_contract_validates or orders_first_party or compatibility_shims"`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_future_repo_ci.py tests/test_future_repo_split_manifest.py`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q packages/codira-bundle-official/tests/test_bundle_package.py tests/test_contracts.py::test_root_optional_dependencies_support_monorepo_bundle_install tests/test_bootstrap_scripts.py -k "first_party_package_inventory or editable_package_paths or build_install_argv_installs_each_first_party_package_editably or release_artifact_helper_covers_core or benchmark_metadata_includes_first_party_plugins or split_repo_verification_installs_local_first_party_packages_for_bundle"`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check ...`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check ...`

### Phase 3

- Added `documentation_artifacts` to schema version 18 with dedicated stable
  identity, provenance, location, heading path, text, and owner fields.
- Added a backend-neutral `documentation_candidates` contract and semantic
  wrapper separate from symbol embedding candidates.
- Persisted documentation artifacts and `object_type = 'documentation'`
  embeddings in SQLite, DuckDB, and the in-memory backend.
- Updated delete, clear, reuse-count, previous-embedding, and orphan-prune
  paths so documentation rows are not left stale and can be reused
  incrementally.
- Added SQLite and DuckDB tests proving docs-only analyses produce no symbol
  candidates while returning documentation candidates.
- Validation:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_contracts.py::test_sqlite_index_backend_persists_documentation_without_symbols tests/test_contracts.py::test_sqlite_index_backend_persists_and_deletes_normalized_analysis packages/codira-backend-duckdb/tests/test_duckdb_backend_package.py::test_duckdb_documentation_candidates_use_stored_vector_values packages/codira-backend-duckdb/tests/test_duckdb_backend_package.py::test_duckdb_embedding_candidates_use_stored_vector_values`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check tests/test_contracts.py packages/codira-backend-duckdb/tests/test_duckdb_backend_package.py tests/memory_backend.py packages/codira-backend-sqlite/src/codira_backend_sqlite packages/codira-backend-duckdb/src/codira_backend_duckdb src/codira/contracts.py src/codira/semantic/search.py src/codira/schema.py`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check tests/test_contracts.py packages/codira-backend-duckdb/tests/test_duckdb_backend_package.py tests/memory_backend.py packages/codira-backend-sqlite/src/codira_backend_sqlite packages/codira-backend-duckdb/src/codira_backend_duckdb src/codira/contracts.py src/codira/semantic/search.py src/codira/schema.py`
