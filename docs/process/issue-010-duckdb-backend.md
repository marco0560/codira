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

* pending

### Phase 3

Goal:
Implement the DuckDB backend lifecycle and persistence/query surfaces.

Status:

* pending

### Phase 4

Goal:
Integrate DuckDB activation and route core/query logic through the backend.

Status:

* pending

### Phase 5

Goal:
Add contract parity and DuckDB-specific integration tests.

Status:

* pending

### Phase 6

Goal:
Run repository validation and fix regressions until green.

Status:

* pending

### Phase 7

Goal:
Document the DuckDB plugin itself plus DuckDB activation and integration in
codira.

Status:

* pending
