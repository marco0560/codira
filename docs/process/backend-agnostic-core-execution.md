# Backend-Agnostic Core Execution Ledger

## Scope

Refactor `codira` so core orchestration is backend agnostic and backend plugins
own concrete storage, persistence, and query implementation details.

## Objectives

1. Remove SQLite-shaped runtime coupling from `codira-core`.
2. Make the SQLite plugin the direct reference backend implementation.
3. Replace DuckDB inheritance from SQLite with a standalone native backend.
4. Tighten Semgrep rules so the backend-agnostic core boundary is enforced.
5. Align architecture and contributor documentation with the final boundary.

## Non-Goals

- changing the operator-facing backend selection model
- supporting multiple active backends in one repository state directory
- weakening existing deterministic query or indexing behavior

## Planned Phases

1. Expand and normalize the backend contract around backend-owned behavior.
2. Move SQLite-owned persistence and query functionality fully behind the
   SQLite plugin package boundary.
3. Replace DuckDB inheritance and shared SQLite helper usage with native
   DuckDB implementations.
4. Remove remaining core storage coupling and backend-shaped SQL ownership.
5. Update Semgrep architecture rules so the new boundary is enforced.
6. Update architecture/process documentation to match the new layout.
7. Validate functional parity and compare backend performance after the cutover.

## Current Known Couplings To Remove

- `src/codira/indexer.py` imports `codira.sqlite_backend_support`
- `packages/codira-backend-duckdb` imports both
  `codira_backend_sqlite.SQLiteIndexBackend` and
  `codira.sqlite_backend_support`
- `src/codira/query/context.py`, `src/codira/query/producers.py`, and
  `src/codira/query/graph_enrichment.py` still expose `sqlite3`-shaped
  connection typing
- Semgrep architecture rules still carry allowlists for current SQLite-shaped
  debt in core

## Validation Target

- `uv run python scripts/validate_repo.py`
- backend contract coverage for SQLite, DuckDB, and memory validation backend
- Semgrep guardrails updated to fail on reintroduced core/backend coupling
- benchmark campaign rerun for both `sqlite` and `duckdb`
