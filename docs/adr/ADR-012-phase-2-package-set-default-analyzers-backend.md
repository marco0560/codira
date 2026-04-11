# ADR-012 — Phase 2 package set for default analyzers and backend

**Date:** 09/04/2026
**Status:** Accepted

## Context

`ADR-007` and `ADR-011` establish the migration order:

* Phase 1 extracts the optional first-party analyzers first.
* Phase 2 then applies the same package-boundary rule to the default
  implementations.

The branch now completes the Phase 1 reconciliation:

* C and Bash are package-owned first-party analyzer distributions.
* runtime discovery now loads those analyzers through Python entry points
  instead of core-side factory wiring
* `codira[bundle-official]` remains the accepted umbrella install contract
  for curated first-party capabilities

Issue `#12` needs a concrete extraction target before files move. Without that
decision, the repository could drift into ad hoc packaging outcomes, for
example:

* extracting Python but leaving JSON as a permanent built-in exception
* keeping the SQLite backend half-owned by core and half-owned by a future
  package
* changing package names or bundle semantics mid-migration

The package set has to be fixed first so Phase 2 code moves, docs, CI, and the
later multirepo split all target the same topology.

## Decision

Adopt the following first-party package set for Phase 2:

* `codira` remains the core platform package
* `codira-analyzer-python` owns the Python analyzer implementation
* `codira-analyzer-json` owns the JSON analyzer implementation
* `codira-backend-sqlite` owns the default SQLite backend implementation
* `codira-analyzer-c` remains the C analyzer distribution from Phase 1
* `codira-analyzer-bash` remains the Bash analyzer distribution from Phase 1
* `codira-bundle-official` remains the curated first-party meta-package

### Core ownership after Phase 2

The `codira` core package remains responsible for:

* contracts
* registry and discovery
* CLI orchestration
* index and query orchestration
* shared models and normalization
* shared storage schema and repository policy
* default selection policy by stable plugin names

Core no longer owns the concrete Python, JSON, or SQLite implementation
modules once Phase 2 is complete.

### Discovery contract

The accepted Phase 2 discovery model is:

* analyzers load through the `codira.analyzers` entry-point group
* backends load through the `codira.backends` entry-point group
* the default implementations are still defaults, but they are defaults by
  selection policy rather than by living in core

### Transition rule

During the monorepo transition, core may keep narrow compatibility surfaces for
historical imports or stable operator errors, but those surfaces must remain:

* import-only
* deterministic
* explicitly transitional

They must not regain implementation ownership.

### Bundle rule

`codira[bundle-official]` stays the accepted umbrella install contract.

`codira-bundle-official` remains the repository-local first-party package
that aggregates the official analyzer and backend distributions for the
published and multirepo end state.

## Consequences

### Positive

* Phase 2 extraction now has fixed package targets before code moves
* JSON is explicitly included in the same rule as Python, avoiding a permanent
  special case
* the later multirepo split can preserve package names instead of deciding them
  during the split
* bundle composition has a stable target before publication work begins

### Negative

* the repository must temporarily carry more first-party package metadata and
  more compatibility surfaces
* default-runtime failures become package-installation problems if bootstrap,
  CI, or docs drift from the accepted package set

### Required follow-up

Issue `#12` must now implement this package set by:

* extracting the Python analyzer implementation
* extracting the JSON analyzer implementation
* extracting the SQLite backend implementation
* updating registry selection and operator-facing errors to match package-owned
  defaults
