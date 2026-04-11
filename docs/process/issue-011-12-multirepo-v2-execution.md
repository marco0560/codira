# Packaging Migration Execution

## Purpose

This ledger records the accepted execution order for the packaging and release
migration leading to `v2.0.0`.

It exists to keep `#11`, `#12`, the multirepo split, `#13`, and the final
publish step aligned to one explicit sequence rather than drifting through
partially overlapping work.

The durable sequencing decision lives in:

* `docs/adr/ADR-011-packaging-release-migration-sequence-v2-0-0.md`

This file is the operational ledger for the work.

## Branch

The long-lived branch for this migration is:

```text
issue-11-12-multirepo-release-plan
```

Concrete implementation slices may still land through smaller working branches
or direct commits rebased onto this branch, but this branch remains the
integration ledger for the overall sequence.

## Accepted Sequence

The accepted order is:

1. `#11`
2. `#12`
3. multirepo split
4. `#13`
5. publish as `v2.0.0`

## Current Baseline

The repository already contains:

* `ADR-007` for the first-party package boundary
* package-owned first-party optional analyzers for C and Bash
* a `codira-bundle-official` package scaffold
* a built-in JSON analyzer that should be treated as part of the future
  default-analyzer package boundary

The remaining work is no longer about deciding whether packaging matters. It is
about executing the accepted boundary cleanly and in the right order.

## Phase 1 — Issue #11

Goal:
Finish the first-party optional-plugin boundary while remaining in the current
repository.

Primary areas:

* bootstrap scripts
* CI workflows
* package metadata
* plugin discovery validation
* user and maintainer docs
* compatibility shims for optional analyzers

Tasks:

- [x] Inventory every remaining compatibility shim for extracted optional
  analyzers in `docs/process/issue-011-optional-plugin-shim-inventory.md`.
- [x] Reconcile repository-local bootstrap with the accepted package boundary.
- [x] Reconcile CI jobs with explicit first-party package installs.
- [x] Align package and install docs with `codira[bundle-official]` and the
  package-owned analyzer model.
- [x] Validate optional analyzer discovery through package metadata and entry
  points, not only source-tree convenience imports.
- [x] Reconcile `ADR-007` Phase 1 ledger state so the only remaining Phase 1
  gate is issue `#11` completion itself.

Exit criteria:

* optional first-party analyzers are treated and documented as real
  distributions
* bootstrap and CI agree with that model
* documentation no longer describes those analyzers as lingering optional
  built-ins

## Phase 2 — Issue #12

Goal:
Apply the same package-boundary rule to the default implementations.

Primary areas:

* Python analyzer ownership
* JSON analyzer ownership
* default SQLite backend ownership
* registry/discovery policy for replaceable defaults
* docs and test inventory

Tasks:

- [x] Define the target first-party package set for default analyzers and the
  default backend in
  `docs/adr/ADR-012-phase-2-package-set-default-analyzers-backend.md`.
- [x] Extract the Python analyzer into its own official distribution.
- [x] Extract the JSON analyzer into its own official distribution.
- [x] Extract the SQLite backend into its own official distribution.
- [x] Keep compatibility and operator-facing errors explicit during the
  transition.
- [x] Update registry/discovery tests for externally replaceable defaults.
- [x] Update install and architecture docs to reflect that defaults are now
  package-provided implementations.
- [x] Remove the remaining core-owned SQLite backend implementation so
  `codira.indexer.SQLiteIndexBackend` is only a compatibility re-export to
  the package-owned class.

Exit criteria:

* Python, JSON, and SQLite backend implementations are package-owned
* core owns orchestration and contracts rather than concrete default
  implementations
* the discovery model is coherent for both default and optional first-party
  packages

## Phase 3 — Multirepo Split

Goal:
Split repositories only after the package contract is already clean.

Primary areas:

* repository ownership boundaries
* package-local CI
* integration testing across repos
* release metadata and docs per repository

Tasks:

- [x] Decide the final repository set for core, analyzers, backend, and bundle
  in `docs/adr/ADR-013-final-multirepo-repository-set-release-coordination-policy.md`.
- [x] Define versioning and release coordination policy across repositories in
  `docs/adr/ADR-013-final-multirepo-repository-set-release-coordination-policy.md`.
- [x] Ensure each future repository builds and tests cleanly from local package
  boundaries before splitting through:
  - `scripts/build_first_party_packages.py`
  - tooling tests in `tests/test_bootstrap_scripts.py`
  - a passing wheel-build validation run against
    `/tmp/codira-first-party-wheels`
- [x] Move package-local tests and package-local docs into their owning
  repository boundaries under `packages/`.
- [x] Recreate CI in each repository as an explicit split-ready contract in:
  - `scripts/future_repo_ci.py`
  - `tests/test_future_repo_ci.py`
  - `docs/process/multirepo-ci-decomposition.md`
- [x] Add integration testing in the core repository using installed package
  artifacts rather than sibling-source loading through
  `tests/test_plugins.py`.
- [x] Define a path-level split manifest for the accepted repository set in:
  - `scripts/future_repo_split_manifest.py`
  - `tests/test_future_repo_split_manifest.py`
  - `docs/process/multirepo-split-manifest.md`
- [x] Add a deterministic export rehearsal helper for one future repository in:
  - `scripts/future_repo_export.py`
  - `tests/test_future_repo_export.py`
  - `docs/process/multirepo-split-manifest.md`

Exit criteria:

* each package builds in isolation
* the split preserves package names and entry-point discovery semantics
* core integration tests no longer depend on monorepo-local source loading

## Phase 4 — Issue #13

Goal:
Remove checkout-local fallback behavior after the multirepo split makes it
unnecessary.

Primary areas:

* analyzer compatibility shims
* registry fallback code
* tests that currently assume source-tree-local package visibility
* bundle alignment

Tasks:

- [x] Remove sibling-source or checkout-local fallback for first-party analyzer
  loading.
- [x] Remove equivalent fallback for default analyzer/backend loading where it
  still exists after `#12`.
- [x] Tighten tests so packages are absent unless installed.
- [x] Align `bundle-official` with the final published package set.
- [x] Update docs to reflect installed-package-only discovery.

Exit criteria:

* discovery relies on installed distributions and entry points only
* no monorepo-local loading path remains
* tests and docs assume the post-split package world

## Phase 5 — Publish `v2.0.0`

Goal:
Publish the final cleaned-up package set only after the topology is stable.

Primary areas:

* build artifacts
* package index upload order
* fresh-environment install validation
* release notes and migration guidance

Tasks:

- [x] Define the `v2.0.0` breaking-change and migration notes in:
  - `docs/process/v2-0-0-migration-notes.md`
  - `docs/process/python-package-publishing-walkthrough.md`
- [x] Add a deterministic wheel+sdist build and `twine check` plan in:
  - `scripts/build_release_artifacts.py`
  - `tests/test_bootstrap_scripts.py`
- [ ] Build wheel and sdist artifacts for every distribution.
- [ ] Run artifact-level validation and fresh-environment install rehearsals.
- [x] Add a wheel-based installed-artifact release rehearsal helper in:
  - `scripts/rehearse_release_installs.py`
  - `tests/test_bootstrap_scripts.py`
- [ ] Publish in dependency order.
- [ ] Verify install, plugin discovery, indexing, and coverage from published
  packages.

Exit criteria:

* published packages reflect the final multirepo topology
* release docs describe one stable install model
* `v2.0.0` validates the final architecture rather than an intermediate state

## Cross-Phase Rules

- [ ] Do not publish the transitional monorepo topology as the canonical final
  install story.
- [ ] Do not split repositories before the package boundary is coherent in the
  monorepo.
- [ ] Keep JSON aligned with the same default-analyzer packaging rule as
  Python unless an explicit ADR says otherwise.
- [ ] Track every transitional shim until it is either removed or justified by
  an updated decision record.

## Release Blockers

These items block the final `v2.0.0` publish until cleared:

- [x] `#11` complete
- [x] `#12` complete
- [ ] multirepo split complete
- [x] `#13` complete
- [ ] publish rehearsals complete
