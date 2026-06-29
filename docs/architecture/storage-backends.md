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
- `packages/codira-backend-duckdb/.../duckdb_query_backend.py` owns the
  DuckDB-local query and maintenance implementation used by the production
  backend

## Index Session Contract

Issue `#30` introduces an explicit split between the backend read path and the
backend write path.

Read-side responsibilities remain on `IndexBackend`:

- loading runtime inventory and analyzer inventory
- loading file hashes and per-file analyzer ownership
- checking embedding backend compatibility
- counting reusable embeddings for unchanged files
- processing pending embeddings for `codira index --embeddings-only`
- serving normal query commands
- reporting whether warm-index maintenance still needs mutation work

Write-side responsibilities now belong to `begin_index_session(root)` and the
returned `IndexWriteSession`:

- purge skipped docstring issues
- prune orphaned embeddings
- load reusable embeddings for paths being replaced
- prepare full or incremental storage replacement
- persist analyzed file snapshots
- queue deferred embedding rows when embedding indexing is deferred
- rebuild derived indexes
- write runtime inventory
- commit, abort, and close

This contract exists to make warm read-heavy command paths cheap while keeping
mutation ownership explicit and backend-local.

## Full-Index Bulk Contract

DuckDB also implements the optional `FullIndexBulkBackend` contract for
`codira index --full`. The core indexer uses it only when both conditions hold:

- the active backend implements `FullIndexBulkBackend`
- the current run is a full rebuild

SQLite intentionally remains on the `IndexWriteSession` path and is the
control backend for performance comparisons.

The DuckDB bulk path owns the complete full-rebuild lifecycle:

- collect successful analyzer output in the core indexer
- validate duplicate stable IDs before backend mutation
- rebuild index-owned DuckDB tables in one backend-native lifecycle
- assign full-rebuild row IDs without per-file `SELECT MAX(id)` allocation
- flush structural, relationship, reference-scan, and embedding rows in
  backend batches
- rebuild derived indexes, persist runtime inventory, and emit DuckDB profile
  spans named `bulk_full_index.*`

The legacy `_store_analysis` helper remains available for incremental and
session-based writes. DuckDB full-index bulk code must call the lower-level row
appending helper instead of routing through `_store_analysis`; Semgrep enforces
that boundary.

Vector stores may optionally implement `VectorStoreBulkWriter` for full-index
materialized vector writes. The DuckDB vector store implements the contract
while preserving the current separated `.codira/embeddings.duckdb` storage file.

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

The current DuckDB backend is no longer coupled to SQLite runtime types or the
SQLite backend package. Its query and maintenance implementation is fully
owned inside the DuckDB package boundary.

## Phase-8 Selection Rules

Phase 8 made backend activation explicit through `src/codira/registry.py`.
Issue #17 moves the persistent selection source into Codira configuration while
preserving the environment variable as a process override.

- the configured backend is read from effective configuration key
  `backend.name`
- `CODIRA_INDEX_BACKEND` overrides config files for the current process
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

## Warm Read Path

Unchanged repositories should not enter writer setup just to confirm the index
is still current.

The accepted warm-path sequence is:

1. inspect runtime inventory through the backend read path
2. inspect analyzer inventory through the backend read path
3. load indexed file hashes and analyzer ownership
4. compare against the current repository scan
5. skip `begin_index_session(...)` only when no file mutations are required
   and the backend reports no maintenance work

Maintenance work still forces a write session even when file contents are
unchanged. Current examples:

- stale shell-owned docstring issues from older audit rules
- orphaned embedding rows left behind by previous storage versions

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

The DuckDB package-local query and maintenance implementation is now the
supported production surface rather than a migration-only compatibility layer.

Issue `#30` also moves DuckDB schema repair for legacy nullable edge tables out
of ordinary read-only opens. Repair now happens when a write session starts,
so `ctx`, `sym`, `calls`, `symlist`, `audit`, and other query commands do not
pay repair cost during warm reads.

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
