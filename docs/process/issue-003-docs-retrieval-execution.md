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
- Provide a docs-only CLI inspection command for documentation retrieval
  debugging and focused documentation queries.
- Index clearly documentation-scoped plain-text `.txt` files.
- Index C/C++ Doxygen module/file and declaration-attached documentation
  through the C/C++ analyzer plugins.

Out of scope for V1:

- Function, class, and method docstring retrieval.
- Arbitrary comment-block harvesting.
- Generic C/C++ block comments.
- Rustdoc, Doxygen, reStructuredText, or other non-Markdown documentation
  formats.
- A docs-only CLI command.

Out of scope after V2:

- Python callable docstring retrieval.
- Arbitrary generic comment harvesting.
- Non-Doxygen C/C++ comments.
- Rustdoc, reStructuredText, and other future documentation formats.

## Phase Ledger

| Phase | Status | Evidence | Commit |
|-------|--------|----------|--------|
| 0. Scope and execution ledger | Complete | Ledger created. | `217e8d4` |
| 1. Models and analyzer contract | Complete | Added `DocumentationArtifact`, documentation literals, and shared row aliases. `uv run ruff check src/codira/models.py src/codira/types.py`; `uv run ruff format --check src/codira/models.py src/codira/types.py`. | `562b9cd` |
| 2. Source extraction | Complete | Markdown analyzer, Python module-doc artifacts, analyzer capability wiring, first-party package wiring, and symbol-index skip guard for documentation-only analyses. Focused analyzer/plugin/package tests and Ruff checks passed. | `a89dfc0` |
| 3. Backend persistence and embeddings | Complete | SQLite, DuckDB, and in-memory backends persist/query docs and doc embeddings through a distinct documentation object type. Focused backend tests and Ruff checks passed. | `9000e0d` |
| 4. `ctx` retrieval and output | Complete | `docs` channel, typed documentation top matches, intent weighting, provenance, explain output, and context JSON schema 1.3. Focused context tests and Ruff checks passed. | `917966e` |
| 5. Validation and cleanup | Complete | Full pre-commit and pytest passed after expectation cleanup. | `6edee25` |
| 6. V2 ranking and docs CLI | Complete | Added behavior-query docs/code quota safeguards, stronger docs path ranking, and `codira docs` inspection command. Focused context, CLI, capability, Ruff, and format checks passed. | `9fc513e`, `5b12b8d` |
| 7. V2 plain-text documents | Complete | Added first-party text analyzer package for path-scoped `.txt` docs with generated, fixture, log, and vendor exclusions. Focused analyzer, plugin, bundle, split-repo, bootstrap, Ruff, format, and mypy checks passed. | `7048fe6` |
| 8. V2 declaration-attached docs | Complete | Extended artifact owner metadata and added C/C++ Doxygen-only documentation artifacts with SQLite, DuckDB, and in-memory backend parity. Focused analyzer, backend, capability, Ruff, format, and mypy checks passed. | `c06ae40` |
| 9. V2 documentation cleanup | Complete | Updated the execution ledger and README command reference to match V2 behavior. | Pending |

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
- Documentation artifacts under `docs/` receive a small merge-time boost, while
  still preserving the docs channel's separate provenance and weighting.
- Backend parity is mandatory for SQLite, DuckDB, and the in-memory backend.

## V2 Implementation

V2 extends the completed V1 feature while preserving the same retrieval
architecture: analyzers emit normalized documentation artifacts, persistence
keeps documentation distinct from symbols, and `ctx` remains the default mixed
retrieval UX.

Implemented V2 phases:

1. Add explicit docs/code diversity quotas and expose quota decisions in
   explain diagnostics.
2. Add stronger path-aware ranking for `docs/process`, `docs/adr`, `README`,
   and `CHANGELOG` documentation.
3. Add a docs-only CLI inspection command that reuses the existing
   `documentation_candidates` contract and does not replace mixed `ctx`
   retrieval.
4. Add a strict plain-text document analyzer for clearly documentation-scoped
   `.txt` files only, excluding fixtures, logs, generated outputs, and vendor
   material by default.
5. Extend documentation artifacts for declaration-attached docs with explicit
   owner identity, owner kind, and attachment confidence.
6. Add C/C++ Doxygen support through the C/C++ analyzer plugins, limited to
   analyzer-proven file/header docs and declaration-attached docs.
7. Keep Python callable docs out of V2.
8. Validate SQLite and DuckDB parity from the start of each persistence/schema
   change.
9. Update repository documentation as a cleanup step so user-facing docs,
   process docs, and implementation behavior remain synchronized.

V2 preserves these V1 boundaries:

- analyzers own source-format parsing
- the query layer consumes normalized documentation artifacts
- arbitrary comment harvesting remains out of scope
- documentation embeddings remain distinct from symbol embeddings
- docs-only retrieval remains an inspection/debug surface, while `ctx` stays the
  default mixed retrieval UX

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

### Phase 4

- Added the `docs` channel to retrieval planning and producer diagnostics.
- Routed documentation candidates through the dedicated backend docs method and
  converted them to explicit `documentation` top matches with provenance.
- Added intent-aware docs weighting: strong for architecture, configuration,
  and API-surface queries; conservative for behavior and test queries.
- Kept graph expansion, reference lookup, docstring issue lookup, and redundant
  module filtering code-symbol-only.
- Added documentation provenance to text rendering, JSON top matches,
  explain-channel results, and merge diagnostics.
- Bumped context JSON schema to `1.3` for documentation provenance fields.
- Validation:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_context_rendering.py tests/test_characterization_phase2.py tests/test_json_schema.py`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check src/codira/query/context.py src/codira/query/classifier.py src/codira/query/producers.py tests/test_context_rendering.py tests/test_characterization_phase2.py tests/test_json_schema.py`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check src/codira/query/context.py src/codira/query/classifier.py src/codira/query/producers.py tests/test_context_rendering.py tests/test_characterization_phase2.py tests/test_json_schema.py`

### Phase 5

- Updated regression expectations for the new Markdown analyzer, schema version
  18, dedicated documentation embeddings, and incremental reuse accounting.
- Re-ran the focused failures from full-suite validation before final checks.
- Validation:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_bootstrap_scripts.py::test_build_helper_rehearses_each_first_party_package_boundary tests/test_contracts.py::test_active_phase_8_registries_expose_default_backend_and_analyzers tests/test_embeddings.py::test_index_repo_persists_symbol_embeddings tests/test_incremental_indexing.py::test_index_repo_reuses_unchanged_symbol_embeddings_in_changed_file tests/test_plugins.py::test_plugins_cli_marks_only_the_configured_backend_active tests/test_plugins.py::test_core_can_discover_installed_first_party_packages_from_built_wheels`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check tests/test_bootstrap_scripts.py tests/test_contracts.py tests/test_embeddings.py tests/test_incremental_indexing.py tests/test_plugins.py`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check tests/test_bootstrap_scripts.py tests/test_contracts.py tests/test_embeddings.py tests/test_incremental_indexing.py tests/test_plugins.py`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pre-commit run --all-files`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`

### Phase 6

- Added a behavior/test intent safeguard so documentation results cannot crowd
  out code results when code candidates exist.
- Exposed docs/code quota diagnostics in explain output.
- Added stronger path-aware ranking for `docs/process`, `docs/adr`, `README`,
  and `CHANGELOG` documentation, while retaining the smaller generic `docs/`
  boost.
- Added `codira docs` as a docs-only inspection command with text, JSON,
  explain, limit, prefix, and storage-path options.
- Validation:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_context_rendering.py tests/test_retrieval_merge.py`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_call_graph.py::test_cli_docs_command_renders_documentation_results tests/test_call_graph.py::test_cli_docs_command_emits_json_results tests/test_call_graph.py::test_cli_docs_command_explain_includes_backend_and_prefix tests/test_call_graph.py::test_help_lists_docs_command tests/test_capabilities.py::test_capabilities_include_docs_command`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check ...`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check ...`

### Phase 7

- Added the first-party `codira-analyzer-text` package and compatibility shim.
- Accepted `.txt` documents only when they are clearly documentation scoped:
  `docs/`, `doc/`, `adr/`, `process/`, or root-style `README.txt`,
  `CHANGELOG.txt`, and `LICENSE.txt`.
- Excluded generated, fixture, log, vendor, build, cache, and artifact trees by
  default.
- Added `plain_text_document` provenance while keeping plain-text artifacts out
  of symbol retrieval.
- Wired the package through the official bundle, first-party inventory,
  split-repo manifests, release/build helpers, benchmark metadata, and plugin
  ordering tests.
- Validation:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q packages/codira-analyzer-text/tests/test_text_package.py packages/codira-bundle-official/tests/test_bundle_package.py tests/test_contracts.py::test_root_optional_dependencies_support_monorepo_bundle_install tests/test_contracts.py::test_active_phase_8_registries_expose_default_backend_and_analyzers tests/test_plugins.py::test_core_can_discover_installed_first_party_packages_from_built_wheels tests/test_plugins.py::test_registry_orders_first_party_analyzers_across_sources tests/test_future_repo_ci.py tests/test_future_repo_split_manifest.py`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/test_bootstrap_scripts.py -k "first_party_package_inventory or editable_package_paths or build_install_argv_installs_each_first_party_package_editably or release_artifact_helper_covers_core or benchmark_metadata_includes_first_party_plugins or split_repo_verification_installs_local_first_party_packages_for_bundle or build_helper_rehearses_each_first_party_package_boundary"`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check ...`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check ...`
  - Commit hook mypy passed.

### Phase 8

- Extended documentation artifacts with `owner_kind` and
  `attachment_confidence`; schema version is now 19.
- Persisted the new metadata in SQLite, DuckDB, and the in-memory contract
  backend.
- Added C and C++ Doxygen-only documentation artifacts for module/file header
  docs and declaration-attached owners.
- Kept generic C/C++ comments out of documentation retrieval.
- Kept Python callable docstrings out of the docs channel.
- Validation:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q packages/codira-analyzer-c/tests/test_c_package.py packages/codira-analyzer-cpp/tests/test_cpp_package.py tests/test_capabilities.py tests/test_contracts.py::test_sqlite_index_backend_persists_documentation_without_symbols packages/codira-backend-duckdb/tests/test_duckdb_backend_package.py::test_duckdb_documentation_candidates_use_stored_vector_values`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check ...`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check ...`
  - `UV_CACHE_DIR=/tmp/uv-cache uv run mypy ...`
  - Commit hook pre-commit checks passed.

### Phase 9

- Updated this execution ledger so the V2 implementation status, behavior
  boundaries, commit evidence, and validation evidence match the repository
  implementation.
- Updated the README command reference for `codira docs`, documentation-aware
  `ctx` behavior, and documentation-only JSON/explain output modes.
