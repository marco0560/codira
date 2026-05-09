# ADR-020 — Backend-isolated repository test policy

**Date:** 09/05/2026
**Status:** Accepted

## Context

`codira` now supports more than one first-party index backend.

The repository test plan includes several kinds of backend-sensitive behavior:

* tests that assert the default backend remains SQLite unless a test chooses a
  different backend explicitly
* tests that exercise backend-neutral indexing and query flows and should stay
  stable regardless of the operator shell environment
* tests that intentionally validate DuckDB-specific compatibility and must run
  with the DuckDB backend selected

During DuckDB hardening, the repository exposed a workflow problem:

* running pytest from a shell with `CODIRA_INDEX_BACKEND=duckdb` changed the
  behavior of unrelated tests that were written with implicit SQLite-default
  assumptions
* placing backend-selection fixtures only under `tests/` would not cover the
  package-local test suites under `packages/*/tests/`

The repository needs one durable policy that explains:

* whether tests may inherit backend selection from the caller shell
* how backend-specific tests must select the backend they intend to validate
* why the shared pytest fixture file lives at repository root rather than only
  under `tests/`

## Decision

Adopt a repository-wide pytest backend-isolation policy.

### Backend environment isolation

Repository tests must not inherit `CODIRA_INDEX_BACKEND` implicitly from the
operator shell.

A shared pytest fixture layer will clear ambient backend overrides before each
test and provide an explicit helper for tests that need to select a backend.

### Fixture placement

The shared backend-isolation fixture file belongs at repository root as
`conftest.py`.

This placement is intentional because the policy must apply to:

* top-level tests under `tests/`
* package-local tests under `packages/*/tests/`

Using only `tests/conftest.py` would leave package-local suites outside the
policy boundary.

### Test-writing rules

Future tests must follow these rules:

* tests that depend on the default backend must select or assert SQLite
  explicitly instead of relying on the caller shell
* tests that are meant to work across backends should set the backend
  explicitly per case, usually through parametrization
* tests that validate DuckDB behavior must select DuckDB explicitly

### Compatibility expectation

DuckDB support is part of the supported repository validation surface.

Repository smoke coverage must therefore continue to exercise both SQLite and
DuckDB for basic indexing and query flows.

## Consequences

### Positive

* test results become independent from the operator shell environment
* backend-default expectations stay explicit and easier to read
* package-local tests and top-level tests follow one consistent policy
* DuckDB compatibility remains visible in normal repository validation

### Negative

* test setup gains one repository-wide pytest harness file
* some existing tests must be more explicit about backend selection

### Neutral / Trade-offs

* this ADR documents a repository workflow and compatibility rule, not a new
  production architecture boundary
* backend isolation should remain local to the test harness unless a future ADR
  changes backend-selection semantics for production code
