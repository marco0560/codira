# Backend-Agnostic Core Execution Ledger

## Scope

Refactor `codira` so core orchestration is backend agnostic and backend plugins
own concrete storage, persistence, and query implementation details.

## Objectives

1. Remove SQLite-shaped runtime coupling from `codira-core`.
2. Make the SQLite plugin the direct reference backend implementation.
3. Replace DuckDB runtime imports of SQLite-owned code with DuckDB-local ownership.
4. Tighten Semgrep rules so the backend-agnostic core boundary is enforced.
5. Align architecture and contributor documentation with the implemented boundary.

## Non-Goals

- changing the operator-facing backend selection model
- supporting multiple active backends in one repository state directory
- weakening existing deterministic query or indexing behavior

## Planned Phases

1. Expand and normalize the backend contract around backend-owned behavior.
2. Move SQLite-owned persistence and query functionality fully behind the
   SQLite plugin package boundary.
3. Replace DuckDB cross-package inheritance and shared SQLite helper usage
   with DuckDB-local implementations.
4. Remove remaining core storage coupling and backend-shaped SQL ownership.
5. Update Semgrep architecture rules so the new boundary is enforced.
6. Update architecture/process documentation to match the new layout.
7. Validate functional parity and compare backend performance after the cutover.

## Implemented Progress

- `src/codira/query/context.py`, `src/codira/query/producers.py`, and
  `src/codira/query/graph_enrichment.py` now use backend-neutral query
  connection protocols
- `packages/codira-backend-sqlite/.../sqlite_support.py` owns the SQLite
  helper implementation
- `packages/codira-backend-sqlite/.../sqlite_storage.py` now owns the
  package-local SQLite bootstrap/path seam used by runtime and SQLite-oriented
  test scaffolding
- DuckDB persistence now uses package-local `duckdb_support.py`
- `packages/codira-backend-duckdb/.../repo_storage.py` now owns the localized
  seam for generic `.codira` directory and metadata path access
- DuckDB no longer imports `codira_backend_sqlite` at runtime
- Semgrep guardrails were updated to match the new package-local ownership
  boundaries
- backend/plugin Semgrep rules now fail direct `codira.storage` imports
  outside the documented package-local seam modules

## Remaining Transitional Surfaces

No runtime migration shims remain in the first-party backend packages. The
DuckDB query and maintenance implementation is now a normal package-local
production surface, and the Semgrep allowlists no longer carry DuckDB-specific
migration exceptions.

## Validation Target

- `uv run python scripts/validate_repo.py`
- backend contract coverage for SQLite, DuckDB, and memory validation backend
- Semgrep guardrails updated to fail on reintroduced core/backend coupling
- performance checkpoint captured for both `sqlite` and `duckdb`

## Current Performance Checkpoint

Lightweight local checkpoint command:

- `uv run python scripts/benchmark_index.py . --output ... --output-dir ...`

Observed on this branch:

- `sqlite` non-full checkpoint completed with `total=56.980669s` and
  `indexing=55.435749s`
- `duckdb` checkpoint was started under an isolated output directory but did
  not complete within the interactive waiting window, so no comparative timing
  claim is recorded yet
