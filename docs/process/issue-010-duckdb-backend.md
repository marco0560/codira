# Issue 010 DuckDB Backend

## Purpose

This ledger records the execution of issue `#10` on branch
`feat/issue-10-duckdb-backend`.

It exists to keep the DuckDB backend work bounded, traceable, and phase-based
while preserving the repository backend contract established by issues `#8`
and `#9`.

## Branch

The working branch for this issue is:

```text
feat/issue-10-duckdb-backend
```

## Decision Set

The fixed decision set for this issue is:

* `D1A` — implement DuckDB as the first additional production-grade backend
* `D2B` — deliver balanced scope: contract hardening where needed plus one
  production backend implementation
* `D3A` — keep activation environment-based
* `D4A` — plan against current repository HEAD and the resolved outcomes of
  issues `#8` and `#9`
* `D5B` — require shared contract parity tests plus DuckDB-specific
  integration tests

## Scope Lock

In scope:

* one new first-party backend package for DuckDB
* backend contract hardening only where required for parity
* env-based backend activation through `CODIRA_INDEX_BACKEND=duckdb`
* parity with SQLite on deterministic observable behavior
* package and integration documentation for DuckDB activation in codira

Out of scope:

* PostgreSQL
* multi-backend-per-repository operation
* system-level DuckDB installation requirements
* new persistent config files for backend selection
* unrelated refactors outside backend integration

## Excluded Existing Worktree Changes

The following pre-existing local changes are excluded from this issue work:

* `docs/adr/ADR-015-codira-development-roadmap.md`
* `scripts/clean_repo.py`
* `guidelines.tar.xz`

## Phase Commit Policy

At least one commit must be created at the end of every completed phase.
Each phase commit must remain scoped to that phase only and must not include
the excluded pre-existing worktree changes.

## Phase Plan

### Phase 0

Goal:
Establish the execution ledger, lock scope, and record the current baseline.

Expected files:

* `docs/process/issue-010-duckdb-backend.md`

Validation target:

* ledger exists and reflects the approved decision set and exclusions

Status:

* complete

Completed work:

* created the execution ledger for issue `#10`
* recorded the fixed decision set
* recorded issue scope and explicit non-goals
* recorded excluded pre-existing worktree changes
* recorded the per-phase commit policy

Deviations from plan:

* none

Validation run:

* manual review of branch name, dirty worktree exclusions, and ledger content

Remaining risks:

* later phase commits must avoid staging the excluded pre-existing changes

### Phase 1

Goal:
Audit the backend contract and query surfaces to identify the minimal DuckDB
blockers.

Expected files:

* `src/codira/contracts.py`
* `src/codira/registry.py`
* `src/codira/indexer.py`
* `src/codira/query/exact.py`
* `src/codira/semantic/search.py`
* `packages/codira-backend-sqlite/src/codira_backend_sqlite/__init__.py`
* `tests/test_contracts.py`
* `tests/test_memory_backend.py`
* `docs/process/issue-010-duckdb-backend.md`

Validation target:

* exact audit list of contract deltas and remaining SQLite-shaped query paths

Status:

* complete

Completed work:

* audited the backend protocol in `src/codira/contracts.py`
* audited query-facing helpers in `src/codira/query/exact.py`
* audited semantic retrieval entry points in `src/codira/semantic/search.py`
* audited index freshness and rebuild logic in `src/codira/cli.py`
* cross-checked contract coverage in:
  * `tests/test_contracts.py`
  * `tests/test_memory_backend.py`
* cross-checked current backend documentation in:
  * `docs/architecture/storage-backends.md`
  * `docs/plugins/backends.md`

Minimal contract delta list:

* add an explicit backend capability declaration surface to `IndexBackend`
  covering issue `#10` requirements such as:
  * persistence mode
  * transaction support
  * concurrency model
  * storage locality
* remove remaining SQLite-shaped public helper signatures from
  `src/codira/query/exact.py` by changing `conn: sqlite3.Connection | None`
  to a backend-neutral connection type
* update `TreeQueryRequest` in `src/codira/query/exact.py` to use a
  backend-neutral connection field
* keep `src/codira/semantic/search.py` unchanged because it already delegates
  through `active_index_backend()`

Remaining SQLite-shaped query and activation paths:

* `src/codira/query/exact.py` still imports `sqlite3` under `TYPE_CHECKING`
  and publishes SQLite-specific connection types in its helper API and
  request object docstrings
* `src/codira/cli.py` still performs SQLite-specific index inspection inside
  `_inspect_index_rebuild_request()` through:
  * `get_db_path(root)`
  * `sqlite3.connect(db_path)`
  * `SELECT name FROM sqlite_master ...`
  * `init_db(root)` for reset/rebuild
* `src/codira/cli.py` still catches `sqlite3.Error` in index refresh flows,
  which prevents fully backend-neutral activation behavior

DuckDB implementation implications:

* indexing orchestration in `src/codira/indexer.py` is already backend-neutral
  enough to support a second production backend
* query delegation in `src/codira/query/exact.py` is structurally correct, so
  the main remaining work is API-neutrality and backend coverage, not
  wholesale query redesign
* CLI index freshness and rebuild logic must be refactored before DuckDB can
  become a first-class active backend for operator-facing commands
* current capability export only describes analyzers and retrieval producers;
  backend capability declarations do not yet exist and must be introduced to
  satisfy the issue requirements explicitly

Deviations from plan:

* none

Validation run:

* `.venv/bin/codira index --explain`
* targeted `codira ctx` retrieval for backend/query coupling
* targeted source inspection with `sed`
* targeted symbol and text inspection with `rg`

Remaining risks:

* backend capability declaration may expand into schema or CLI output changes
* CLI rebuild/reset semantics are currently tied to SQLite storage helpers and
  may require a new backend-owned freshness/reset abstraction

### Phase 2

Goal:
Scaffold the first-party DuckDB backend package and packaging metadata.

Status:

* complete

Completed work:

* created the new first-party package scaffold:
  * `packages/codira-backend-duckdb/pyproject.toml`
  * `packages/codira-backend-duckdb/README.md`
  * `packages/codira-backend-duckdb/src/codira_backend_duckdb/__init__.py`
  * `packages/codira-backend-duckdb/tests/test_duckdb_backend_package.py`
* fixed the package dependency policy to:
  * `duckdb>=1.4,<2.0`
* fixed the package version to:
  * `1.5.3`
* added the DuckDB backend package to the first-party package inventory in
  `scripts/first_party_packages.py`
* added DuckDB to the curated bundle package metadata in:
  * `packages/codira-bundle-official/pyproject.toml`
  * `pyproject.toml`
* added the backend package hint:
  * `duckdb -> codira-backend-duckdb`
  in `src/codira/registry.py`
* added first-party package inventory coverage for DuckDB in:
  * `scripts/future_repo_ci.py`
  * `scripts/future_repo_split_manifest.py`
  * `scripts/verify_exported_split_repos.py`
  * `scripts/benchmark_timing.py`
* updated the directly impacted inventory and bundle tests

Scaffold constraints:

* the package currently exposes a registry-compatible scaffold backend only
* `DuckDBIndexBackend` intentionally fails fast through `BackendError`
  until lifecycle and query behavior are implemented in later phases
* the package is discoverable and package-testable, but not yet a usable
  production backend

Deviations from plan:

* package-local tests needed a source-tree import path insertion because the
  new package is not installed editably by default in the current environment
* benchmark metadata tests were kept aligned to installed first-party plugins,
  while the authoritative first-party inventory now includes DuckDB

Validation run:

* `.venv/bin/pytest -q packages/codira-backend-duckdb/tests packages/codira-bundle-official/tests/test_bundle_package.py tests/test_future_repo_ci.py tests/test_future_repo_split_manifest.py`
* `.venv/bin/pytest -q tests/test_bootstrap_scripts.py -k "first_party_package_inventory or editable_package_paths or benchmark_metadata_includes_first_party_plugins or split_repo_verification_uses_local_core_checkout"`

Remaining risks:

* the scaffold backend still lacks concrete DuckDB lifecycle, persistence, and
  query behavior
* first-party inventory now references DuckDB, so later phases must keep
  package and tooling metadata synchronized as implementation details land

### Phase 3

Goal:
Implement the DuckDB backend lifecycle and persistence/query surfaces.

Status:

* complete

Completed work:

* replaced the scaffold-only package module with a real `DuckDBIndexBackend`
  implementation
* implemented a DuckDB-specific connection/bootstrap layer in
  `packages/codira-backend-duckdb/src/codira_backend_duckdb/__init__.py`
* kept the DuckDB backend aligned to the existing SQLite backend contract by
  subclassing `SQLiteIndexBackend`
* introduced a minimal connection adapter that:
  * exposes `execute`, `executemany`, `commit`, and `close`
  * provides cursor-style `fetchone`, `fetchall`, and `lastrowid` behavior
    required by shared persistence helpers
* implemented DuckDB-specific storage initialization:
  * database path under `.codira/index.duckdb`
  * sequence-backed identifier DDL for tables that require generated integer
    primary keys
  * schema metadata writing under `.codira/metadata.json`
* implemented package-local overrides for:
  * `initialize`
  * `open_connection`
  * `persist_analysis`
  * `persist_runtime_inventory`
* kept the inherited SQLite query and persistence surface for methods whose
  behavior is driven by backend-neutral SQL and the shared helper layer
* added package-local tests for:
  * rewritten DuckDB schema DDL
  * initialization metadata/bootstrap behavior
  * missing-database initialization through `open_connection`

Implementation choice:

* Phase 3 uses a minimal-subclass strategy rather than forking the full SQLite
  backend implementation
* DuckDB-specific behavior is confined to:
  * dependency loading
  * connection adaptation
  * database path and bootstrap
  * error translation for persistence entry points

Deviations from plan:

* real end-to-end DuckDB execution is not yet validated in this environment
  because the optional `duckdb` dependency is not installed locally
* package-local tests therefore use a fake DuckDB module to validate bootstrap
  and adapter behavior deterministically

Validation run:

* `python -m compileall packages/codira-backend-duckdb/src/codira_backend_duckdb/__init__.py`
* `python -m compileall packages/codira-backend-duckdb/tests/test_duckdb_backend_package.py`
* `.venv/bin/pytest -q packages/codira-backend-duckdb/tests`

Remaining risks:

* runtime compatibility with the real DuckDB Python client still needs
  end-to-end execution validation once the dependency is installed
* inherited SQLite query SQL may expose DuckDB-specific behavioral differences
  only when exercised against a real database file
* CLI index inspection remains SQLite-shaped and is still deferred to the next
  integration phase

### Phase 4

Goal:
Integrate DuckDB activation and route core/query logic through the backend.

Status:

* complete

Completed work:

* removed SQLite-only backend initialization from `src/codira/cli.py` by
  routing both:
  * `codira index`
  * automatic `_ensure_index()` refreshes
  through `active_index_backend().initialize(root)`
* rewrote `_inspect_index_rebuild_request()` in `src/codira/cli.py` to use
  backend-owned hooks instead of SQLite-only probes:
  * metadata read via existing CLI metadata helpers
  * backend connection opening through `active_index_backend()`
  * runtime inventory via `load_runtime_inventory()`
  * analyzer inventory via `load_analyzer_inventory()`
  * indexed file counting via `load_existing_file_hashes()`
  * backend connection teardown via `close_connection()`
* removed the remaining SQLite-shaped public connection typing from
  `src/codira/query/exact.py` by changing the exact-query helper surface and
  `TreeQueryRequest` to use backend-neutral connection handles
* expanded CLI error handling in `src/codira/cli.py` to include
  `codira.contracts.BackendError` so non-SQLite backend failures surface
  through the existing concise CLI diagnostics
* added focused regression coverage in `tests/test_incremental_indexing.py`
  for:
  * `codira index` using the active backend initialization contract
  * index freshness inspection using opaque backend connections instead of
    SQLite-specific connection methods

Deviations from plan:

* the repository-local virtual environment currently imports an installed
  `codira` package rather than the modified workspace source by default
* Phase 4 validation therefore used an explicit `PYTHONPATH` pointing at the
  workspace `src/` trees so the checks exercised the changed code paths

Validation run:

* `PYTHONPATH=src:packages/codira-backend-sqlite/src:packages/codira-backend-duckdb/src .venv/bin/python -m pytest -q tests/test_incremental_indexing.py -k "run_index_initializes_the_active_backend or inspect_index_rebuild_request_uses_backend_connection_contract or ensure_index_rebuilds_when_backend_inventory_changes or ensure_index_missing_db_writes_schema_and_commit_metadata"`
* `PYTHONPATH=src:packages/codira-backend-sqlite/src:packages/codira-backend-duckdb/src .venv/bin/python -m pytest -q packages/codira-backend-duckdb/tests/test_duckdb_backend_package.py`

Remaining risks:

* default CLI and pytest invocation in the current `.venv` still resolve the
  installed `codira` package unless the workspace source is installed or
  added to `PYTHONPATH`
* full end-to-end active-backend validation with a real DuckDB dependency is
  still deferred to later phases

### Phase 5

Goal:
Add contract parity and DuckDB-specific integration tests.

Status:

* complete

Completed work:

* extended `packages/codira-backend-duckdb/tests/test_duckdb_backend_package.py`
  with backend-specific integration coverage for:
  * runtime inventory persistence and round-trip loading
  * analyzer inventory persistence and deterministic ordering
  * driver-error translation from DuckDB-specific failures to
    `codira.contracts.BackendError`
* added registry-selection coverage in `tests/test_plugins.py` proving that:
  * `CODIRA_INDEX_BACKEND=duckdb` resolves through the normal backend
    entry-point path
  * the DuckDB backend is reported as a first-party plugin registration
* added contract-level missing-package-hint coverage in `tests/test_contracts.py`
  proving that a configured-but-missing DuckDB backend reports:
  * `codira-backend-duckdb`
  * `codira-bundle-official`
  in the operator-facing error message

Deviations from plan:

* the real optional `duckdb` dependency is still not installed in this
  environment
* Phase 5 therefore did not add a full SQLite-vs-DuckDB observable parity run
  through the real indexer and a real DuckDB file
* instead, this phase added the strongest executable coverage currently
  available:
  * backend-specific persistence/inventory tests using a deterministic fake
    driver surface
  * core registry and operator-facing activation tests for the DuckDB backend

Validation run:

* `PYTHONPATH=src:packages/codira-backend-sqlite/src:packages/codira-backend-duckdb/src .venv/bin/python -m pytest -q packages/codira-backend-duckdb/tests/test_duckdb_backend_package.py tests/test_plugins.py tests/test_contracts.py -k "duckdb or active_default_backend_comes_from_first_party_sqlite_package"`
* `.venv/bin/pre-commit run --all-files`

Remaining risks:

* real driver behavior for end-to-end indexing and query parity against
  SQLite still needs validation once `duckdb` is installed in the active
  environment
* future documentation-channel scale tests are still deferred because they
  need the real backend implementation exercised against a real database file

### Phase 6

Goal:
Run repository validation and fix regressions until green.

Status:

* complete

Completed work:

* ran the repository validation surface on the branch:
  * `.venv/bin/pre-commit run --all-files`
  * `.venv/bin/pytest -q`
* fixed stale bootstrap/release expectation tests in
  `tests/test_bootstrap_scripts.py` so they now reflect DuckDB as part of the
  first-party package inventory and split-repo/release command plans
* stabilized the Phase 4 incremental-indexing tests in
  `tests/test_incremental_indexing.py` by loading the workspace `src/codira/cli.py`
  module explicitly during the affected assertions, avoiding false negatives
  from the installed package shadowing the working tree in the current `.venv`
* stabilized the DuckDB missing-package-hint test in `tests/test_contracts.py`
  by loading the workspace `src/codira/registry.py` module explicitly for the
  affected assertion
* resolved final lint/type issues introduced by the test helpers so the full
  `pre-commit` surface passes again

Deviations from plan:

* Phase 6 did not require production code changes
* the only stabilization needed after Phases 4 and 5 was in validation/tests:
  * expectation updates for the expanded first-party package set
  * explicit workspace-module loading in tests that must exercise branch-local
    code while the active virtual environment still prefers an installed
    `codira` package

Validation run:

* `.venv/bin/pre-commit run --all-files`
* `.venv/bin/pytest -q`

Final validation state:

* `pre-commit`: passed
* `pytest -q`: passed (`332 passed`)

Remaining risks:

* the current virtual environment still prefers an installed `codira` package
  for ordinary imports; tests that must target branch-local source need the
  explicit workspace-module loading approach used here unless the editable
  install is refreshed
* real DuckDB-driver end-to-end parity against SQLite is still pending the
  actual `duckdb` dependency in the active environment

### Phase 7

Goal:
Document the DuckDB plugin itself plus DuckDB activation and integration in
codira.

Status:

* complete

Completed work:

* updated `packages/codira-backend-duckdb/README.md` to document:
  * `pip` installation
  * repository-local editable install
  * activation through `CODIRA_INDEX_BACKEND=duckdb`
  * verification commands
  * operator fit and non-goals
* updated `docs/plugins/backends.md` to document:
  * the current first-party backend set
  * environment-based backend activation
  * default-backend behavior
  * DuckDB-specific usage guidance
* updated `docs/plugins/getting-started.md` to make backend activation explicit
  and to include a first-party DuckDB example
* updated `docs/architecture/storage-backends.md` to reflect:
  * SQLite and DuckDB as the current first-party backend set
  * one-backend-per-repository operation
  * DuckDB’s role as the local analytical/document-heavy backend option
  * shared rebuild-policy metadata across the supported backends

Deviations from plan:

* none

Validation run:

* manual documentation review for consistency against:
  * `src/codira/registry.py`
  * `packages/codira-backend-duckdb/src/codira_backend_duckdb/__init__.py`
  * the approved issue decision set recorded in this ledger
* `.venv/bin/pre-commit run --all-files`

Remaining risks:

* documentation now reflects the implemented backend activation path, but real
  end-to-end DuckDB operational guidance may still need expansion once the
  optional `duckdb` dependency is exercised routinely in the active
  development environment
