# ADR-013 — Final multirepo repository set and release coordination policy

**Date:** 09/04/2026
**Status:** Accepted

## Context

`ADR-011` fixes the execution order for the `v2.0.0` migration:

1. finish `#11`
2. finish `#12`
3. perform the multirepo split
4. remove monorepo-local fallback in `#13`
5. publish

`ADR-012` then fixes the Phase 2 package set that the split must preserve:

* `codira`
* `codira-analyzer-python`
* `codira-analyzer-json`
* `codira-analyzer-c`
* `codira-analyzer-bash`
* `codira-backend-sqlite`
* `codira-bundle-official`

Before the split starts, the repository needs two explicit decisions:

* which repositories will exist after the split
* how versions and release coordination should work for the initial clean
  publish

Without those decisions, Phase 3 can drift into avoidable churn:

* moving the bundle in or out of the core repository late
* changing ownership boundaries while files are already being split
* mixing independent versioning with a coordinated `v2.0.0` launch
* creating CI and release automation that targets the wrong repository set

## Decision

Adopt the following final repository set for the post-split topology:

* `codira`
  Core platform repository for contracts, registry/discovery, CLI,
  orchestration, schema/storage, query flow, and shared utilities.
* `codira-analyzer-python`
  First-party Python analyzer repository.
* `codira-analyzer-json`
  First-party JSON analyzer repository.
* `codira-analyzer-c`
  First-party C analyzer repository.
* `codira-analyzer-bash`
  First-party Bash analyzer repository.
* `codira-backend-sqlite`
  First-party SQLite backend repository.
* `codira-bundle-official`
  First-party meta-package repository that aggregates the official analyzers
  and backend.

### Repository ownership rule

Each repository owns exactly one published distribution, except `codira`,
which owns the core distribution and the cross-package integration tests that
validate the installed-package topology.

The split must preserve existing distribution names and entry-point group
contracts.

### Initial release coordination rule

The first clean post-split publish is a coordinated `v2.0.0` release train:

* every first-party repository publishes a `2.0.0` release for the initial
  multirepo launch
* release notes are coordinated across repositories
* dependency pins and lower bounds are updated so the first published
  multirepo set resolves coherently in a fresh environment

### Versioning rule after the initial release

After the coordinated `v2.0.0` launch:

* each split repository may evolve independently
* repository-local tags become the source for future release cadence
* version divergence is allowed when justified by package-local changes

The coordinated release train is required for the first clean launch only. It
is not a permanent lockstep versioning rule.

### CI and integration rule

After the split:

* each package repository must build and test in isolation
* the `codira` core repository must retain integration coverage that
  installs the first-party packages as artifacts, not as sibling-source trees
* `codira-bundle-official` must be validated as a real install target, not
  only as metadata declared inside the core repository

## Consequences

### Positive

* Phase 3 now has a fixed repository target instead of an open-ended split
* the initial `v2.0.0` publish can be rehearsed as one coordinated launch
* package names and ownership stay aligned with the already accepted Phase 2
  package boundary
* bundle ownership is explicit instead of remaining an implicit sidecar in the
  core repository

### Negative

* the split will require more repository bootstrap and CI setup than a
  smaller “core plus plugins only” topology
* release preparation remains coordinated through the first post-split launch,
  which increases short-term operational overhead

### Required follow-up

Phase 3 work must now:

* prepare each future repository to build from its package-local boundary
* move package-local tests and docs into their owning repositories where
  appropriate
* keep cross-package integration validation in `codira`
* use this repository set and coordinated `v2.0.0` policy in the execution
  ledger and release checklist
