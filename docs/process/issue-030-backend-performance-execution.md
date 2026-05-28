# Issue #30 Backend Performance Execution Ledger

## Purpose

Track the implementation of issue `#30` on branch
`feat-issue-30-backend-contract-duckdb` as one architecture and performance
change set.

This ledger records:

- backend contract changes
- indexer lifecycle changes
- backend-specific implementation decisions
- benchmark artifacts and acceptance checks
- validation and merge evidence

## Branch

```text
feat-issue-30-backend-contract-duckdb
```

## Constraints

- all implementation work stays on the issue branch until the end
- final merge must use a repo-hook-compliant commit message and close `#30`
- all docstrings must satisfy the repository NumPy-style contract
- finish with `uv run codira audit` and fix all findings

## Work Items

- [x] Create dedicated branch for the issue
- [x] Audit current backend contract and implementation precedents
- [x] Add explicit backend write-session contract
- [x] Refactor core indexing around the write session
- [x] Port SQLite to the new contract
- [x] Port memory backend to the new contract
- [x] Rework DuckDB writer and cheap-read path
- [x] Update backend docs and benchmark workflow docs
- [x] Add or update subsystem tests
- [ ] Run benchmarks and record artifacts
- [x] Run full validation
- [x] Run `uv run codira audit` and fix all flagged docstrings
- [ ] Merge with issue-closing commit block

## Status Notes

- 2026-05-20: Branch created and execution started.
- 2026-05-20: Added the explicit `IndexWriteSession` contract and moved
  backend mutation ownership out of the core index loop.
- 2026-05-20: Reworked `index_repo()` so incremental planning, runtime
  inventory comparison, and analyzer inventory comparison happen on the
  backend read path before writer setup.
- 2026-05-20: Added backend maintenance checks so unchanged warm runs skip the
  writer only when stale shell docstring issues and orphaned embeddings are
  already absent.
- 2026-05-20: Moved DuckDB nullable-edge repair out of normal query opens and
  into write-session startup.
- 2026-05-20: Changed the DuckDB write session to own one run-scoped
  transaction instead of opening a fresh transaction for each persisted file.
- 2026-05-20: Focused regression coverage is green for incremental indexing,
  backend contract parity, memory backend parity, and DuckDB package behavior.
- 2026-05-20: Full validation is green: `uv run pre-commit run --all-files`,
  `uv run python -m pytest -q`, `uv run codira index`, and
  `uv run codira audit --json`.
- 2026-05-20: Benchmark evidence is still incomplete. The attempted
  `issue-30-short-sqlite` campaign materialized branch-local artifacts only for
  the `small-codira` leg before the runner stopped producing a trustworthy
  finished artifact set. The fallback `issue-30-codira-only-sqlite` campaign
  created its plan and selection artifacts but did not yet produce a completed
  hyperfine result during this execution window.
- 2026-05-21: Investigated the repeated DuckDB benchmark failure and reproduced
  it locally with the exact sequence `benchmark_index.py --full` followed by
  `codira index --full` against the same output directory.
- 2026-05-21: Root cause is the new run-scoped DuckDB transaction added on this
  branch. DuckDB rejects the full-table `clear_index()` delete sequence on a
  populated database when it runs inside one explicit transaction, even though
  the same delete order succeeds in autocommit mode.
- 2026-05-21: Fixed the DuckDB full-rebuild path so `prepare(full=True)` rolls
  back the empty session transaction, clears the populated database in
  autocommit mode, then starts a fresh transaction for the remainder of the
  indexing run.
- 2026-05-21: Added a package-local regression test for clearing a populated
  DuckDB database through the real index-session API and revalidated the exact
  double-full repro sequence successfully.
- 2026-05-21: Hardened the SQLite plugin to enable `PRAGMA foreign_keys = ON`
  on every opened connection so SQLite no longer silently tolerates invalid
  backend clear-order assumptions.
- 2026-05-21: Added SQLite package-local regression coverage for foreign-key
  enforcement on open and for clearing a populated database through the real
  index-session API under the hardened SQLite connection semantics.
- 2026-05-21: The hardened SQLite path exposed a second latent bug in
  per-file deletion: `delete_paths()` was not removing `call_edges` and
  `callable_refs` rows that still referenced the owning `files.id`.
- 2026-05-21: Fixed file-owned edge-row deletion in both SQLite and DuckDB and
  added package-local regression tests so backend-level file deletion now
  removes those rows before deleting the file record itself.
- 2026-05-21: Triaged the branch-local Semgrep output. Fixed the real
  code-level findings by replacing SHA1-based analyzer disambiguation suffixes
  with SHA256 and bumping the affected analyzer-internal versions so stale
  indexes rebuild deterministically.
- 2026-05-21: Added explicit identifier validation plus narrow `nosemgrep`
  suppressions for DuckDB SQL maintenance/query sites that interpolate only
  repository-owned identifier fragments. The remaining branch-local Semgrep
  output is dependency/supply-chain review, not application-code behavior.
- 2026-05-21: Added the last narrow Semgrep suppressions for SQLite prefix
  query builders, DuckDB placeholder-based maintenance deletes, and the two
  remaining DuckDB query-builder sinks. `uv run --no-sync python
  scripts/validate_repo.py` is green again with 341 passing tests and zero
  repository Semgrep findings.
