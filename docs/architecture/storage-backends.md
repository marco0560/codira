# Storage Backends

The current repository has two concrete first-party backends:

- SQLite
- DuckDB

## Current Backend Responsibilities

Backends currently own:

- schema creation and refresh for their concrete storage file
- indexing-side persistence orchestration behind the `IndexBackend` contract
- exact-query execution exposed through backend methods
- embedding inventory reads and candidate retrieval exposed through backend
  methods
- repository-local storage paths under `.codira/`
- persisted runtime plugin inventory and per-file analyzer ownership metadata

Current package-local ownership notes:

- `packages/codira-backend-sqlite/.../sqlite_support.py` owns the SQLite
  helper implementation
- `packages/codira-backend-sqlite/.../sqlite_storage.py` owns the SQLite
  package-local bootstrap and path entrypoints used by the production backend
- `packages/codira-backend-duckdb/.../duckdb_support.py` owns the DuckDB
  persistence helper implementation
- `packages/codira-backend-duckdb/.../repo_storage.py` owns the DuckDB-local
  seam for generic `.codira` directory and metadata path access
- `packages/codira-backend-duckdb/.../duckdb_query_backend.py` is a temporary
  DuckDB-local query/maintenance mixin while the standalone rewrite
  continues

## Current Constraints

The accepted backend model is still constrained:

- one active backend per repository instance
- backend-neutral orchestration above the concrete storage implementation
- deterministic query and indexing semantics preserved across backends
- no multi-backend live switching inside one repository state directory

DuckDB is intentionally file-local, not a shared remote service backend.
Its role is to provide a second production-grade backend with stronger local
analytical behavior for larger indexes, including future documentation-heavy
channels.

The current DuckDB backend is no longer coupled to the SQLite backend package
at runtime, but it still carries a localized SQLite-compatible query layer
inside the DuckDB package while parity-preserving migration continues.

## Phase-8 Selection Rules

Phase 8 makes backend activation explicit through `src/codira/registry.py`.

- the configured backend is read from `CODIRA_INDEX_BACKEND`
- the default backend is `sqlite`
- unsupported names fail fast with `ValueError`
- all current indexing and query entry points resolve the backend through the
  registry instead of constructing it ad hoc

## Accepted Migration Direction

The accepted target is not “many active backends at once”. The accepted target
is:

- one active backend per repository instance
- backend-neutral contracts above the concrete storage implementation
- preserved deterministic query and indexing semantics

Current first-party backend roles:

- `sqlite`
  - default backend
  - smallest operational surface
  - file-local repository storage under `.codira/index.db`
- `duckdb`
  - optional backend selected through `CODIRA_INDEX_BACKEND=duckdb`
  - file-local repository storage under `.codira/index.duckdb`
  - better fit for larger local analytical or document-heavy indexes

Phase 20 extends backend persisted state with:

- analyzer ownership columns on `files` rows
- one-row runtime inventory for backend name, backend version, and coverage
  completeness
- analyzer inventory rows carrying analyzer versions and discovery-glob
  snapshots

Phase 21 makes SQLite use that metadata for deterministic rebuild policy:

- per-file analyzer ownership participates in incremental reuse decisions
- backend runtime inventory mismatches trigger automatic rebuilds
- analyzer inventory mismatches trigger automatic rebuilds

DuckDB follows the same rebuild policy through the same runtime and analyzer
inventory contract.

## Current Boundary Status

The branch-local backend-agnostic refactor has established these boundaries:

- core query modules now type backend connections through backend-neutral
  query protocols rather than `sqlite3.Connection`
- SQLite helper ownership has moved behind the SQLite backend package boundary
- SQLite bootstrap and database-path entrypoints are now package-local backend
  seams rather than direct backend imports of `codira.storage`
- DuckDB persistence no longer routes through the SQLite helper module
- DuckDB no longer imports `codira_backend_sqlite` at runtime
- benchmark and SQLite-oriented test scaffolding now route setup through the
  SQLite backend package seam rather than calling core SQLite bootstrap

The remaining transitional surfaces are explicit:

- DuckDB still uses a package-local SQLite-compatible query layer rather than
  a fully native DuckDB query implementation

## Contributor Contract Validation Backend

Issue #9 adds a minimal in-memory backend for contributor-facing contract
validation. It lives in `tests/memory_backend.py` and is covered by
`tests/test_memory_backend.py`.

Use the in-memory backend when changing code that may affect the
`IndexBackend` contract or observable backend behavior, including:

- `src/codira/contracts.py`
- `src/codira/indexer.py`
- backend registry selection in `src/codira/registry.py`
- query-facing backend methods such as symbol lookup, docstring issues, call
  edges, callable references, include edges, and embedding inventory
- indexing lifecycle behavior such as full rebuilds, incremental reuse,
  deletion, runtime inventory, and analyzer inventory

The backend is intentionally not a production backend:

- it is not distributed as a `codira-backend-memory` package
- it is not available from normal installs
- it is not selected by running `CODIRA_INDEX_BACKEND=memory codira index`
- it does not persist data outside the Python process

Tests select it by installing a fake `codira.backends` entry point or by
patching the active backend in the real indexing path. This keeps the registry
and indexer contract exercised without presenting `memory` as a supported
operator-facing backend.

When extending the backend contract, update both the SQLite backend and the
in-memory backend. Contract tests should compare observable behavior between
SQLite and memory rather than SQLite internals, so regressions expose hidden
coupling to SQL tables, row ids, or SQLite-specific query behavior.
