# ADR-011 — Packaging and release migration sequence for v2.0.0

**Date:** 09/04/2026
**Status:** Accepted

## Context

`ADR-007` fixed the Phase 1 direction for first-party optional analyzers:

* keep one repository for the transition
* move official optional analyzers into package-owned distributions under
  `packages/`
* keep the default Python analyzer and default SQLite backend in core until a
  later phase

Since then the repository has advanced further:

* the C and Bash analyzers are package-owned first-party distributions
* `codira[bundle-official]` is already established as the accepted umbrella
  install contract
* the built-in JSON analyzer now exists with enough family-specific behavior
  that it should be considered part of the future default-analyzer packaging
  boundary, not a special permanent exception

The remaining migration still spans multiple linked issues:

* `#11` finishes the Phase 1 package-boundary reconciliation
* `#12` extracts the default implementations into replaceable distributions
* the repository may then move from monorepo to multirepo
* `#13` removes the current checkout-local fallback once sibling-source loading
  is no longer required

The ordering matters because each step changes the packaging contract that the
next step depends on. Publishing too early would validate an intermediate
topology that is intentionally transitional, while splitting repositories too
early would combine package-boundary changes with repository-boundary changes
in one risky move.

## Decision

Adopt the following migration sequence for the clean `v2.0.0` release:

1. Complete issue `#11` in the current repository.
2. Complete issue `#12` in the current repository.
3. Perform the multirepo split only after the Phase 2 package boundary is
   already coherent.
4. Complete issue `#13` after the multirepo split removes the need for
   sibling-source loading.
5. Publish the resulting package set as `v2.0.0`.

### Phase responsibilities

#### Issue `#11`

Phase 1 must finish the first-party optional-plugin boundary without changing
the repository topology yet.

That includes:

* bootstrap reconciliation
* CI reconciliation
* package-boundary documentation alignment
* validation that the optional first-party analyzers behave like real package
  distributions rather than lingering optional built-ins

#### Issue `#12`

Phase 2 must apply the same package-boundary rule to the default
implementations.

This phase should cover:

* the Python analyzer
* the built-in JSON analyzer
* the default SQLite backend

The goal is to make "default" mean default selection policy, not "lives in the
core source tree."

#### Multirepo split

The repository split is allowed only after the package contract is already
clean inside the monorepo. The split must preserve package names,
entry-point-based discovery, and integration semantics.

The split is a repository-topology change, not a hidden package-contract
rewrite.

#### Issue `#13`

Issue `#13` must remove checkout-local or sibling-source fallback behavior
after the multirepo split has made that fallback unnecessary.

The accepted post-`#13` discovery contract is:

* installed package metadata
* Python entry points
* explicit operator-facing errors when required packages are absent

### Release boundary

The first public release that should present the fully cleaned-up package and
repository topology is `v2.0.0`.

That release must happen only after:

* the package boundary is coherent
* the repository split is complete
* fallback loading is removed
* docs and release tooling reflect the final install story

## Consequences

### Positive

* the published release validates the final topology rather than an
  intermediate state
* repository split risk is separated from the earlier package-boundary work
* `#13` gains a clean removal condition through the multirepo transition
* release notes for `v2.0.0` can document one stable migration target

### Negative

* first real package-index publication is deferred until late in the migration
* more local artifact testing is required before the final publish step
* the monorepo must carry compatibility surfaces longer during `#11` and `#12`

### Required discipline

Because publication is deferred, every phase before `v2.0.0` must add strong
pre-publish validation:

* build-from-artifact checks
* package-install integration tests
* explicit ledger tracking of remaining shims and release blockers

This ADR does not replace issue execution tracking. The detailed step plan and
phase ledger live in the companion process document for this migration branch.
