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

* pending

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
