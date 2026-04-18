# Storage Backends

The current repository has one concrete backend: SQLite.

## Current Backend Responsibilities

SQLite currently owns:

- schema creation and refresh in `src/codira/storage.py`
- indexing-side persistence orchestration through `SQLiteIndexBackend` in
  `src/codira/indexer.py`
- exact-query execution in `src/codira/query/exact.py`
- embedding inventory reads in `src/codira/query/exact.py`
- embedding vector retrieval for semantic search in
  `src/codira/semantic/search.py`
- repository-local storage paths under `.codira/`
- persisted runtime plugin inventory and per-file analyzer ownership metadata

## Current Constraints

The codebase still assumes SQLite-specific details in multiple layers:

- `SQLiteIndexBackend` still persists directly to SQLite-oriented tables
- exact-query helpers open raw SQLite connections
- semantic search reads stored embedding blobs from SQLite rows

Phase 4 reduces the indexing-side coupling by routing `index_repo()` through a
concrete backend object and by persisting normalized `AnalysisResult`
artifacts, but query paths remain SQLite-specific until Phase 7.

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

Phase 20 extends the SQLite backend's persisted state with:

- analyzer ownership columns on `files` rows
- one-row runtime inventory for backend name, backend version, and coverage
  completeness
- analyzer inventory rows carrying analyzer versions and discovery-glob
  snapshots

Phase 21 makes SQLite use that metadata for deterministic rebuild policy:

- per-file analyzer ownership participates in incremental reuse decisions
- backend runtime inventory mismatches trigger automatic rebuilds
- analyzer inventory mismatches trigger automatic rebuilds

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
