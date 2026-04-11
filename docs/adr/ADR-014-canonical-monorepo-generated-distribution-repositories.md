# ADR-014 — Canonical monorepo with generated distribution repositories

**Date:** 11/04/2026
**Status:** Accepted

## Context

The project is moving toward separately published first-party distributions
for the core tool, official analyzers, SQLite backend, and official bundle.
`ADR-013` fixed the target repository set for that post-split topology.

The first real split rehearsal showed that package publication can be
separated from day-to-day development, but it also exposed the maintenance
cost of immediately treating every split repository as an autonomous source
repository:

* core and plugin APIs are still evolving together
* cross-package refactors remain frequent and cheaper in one tree
* release versions are still coordinated across the package set
* contributors need one clear source of truth while the public brand and
  package names are being finalized
* isolated plugin repositories require duplicated CI, release, cleanup, and
  contributor workflows

At the same time, package indexes and downstream users benefit from separate
distributions and separately addressable repository snapshots.

## Decision

Keep the main repository as the canonical development source of truth for the
core package and first-party packages.

Split repositories are generated distribution repositories. They exist to make
published packages independently inspectable, cloneable, buildable, and
testable, but they are not the primary development location while the plugin
API, release process, and public brand remain in flux.

The generated split repositories must be professional enough to survive in the
wild:

* each repository owns exactly one distribution
* each repository has package metadata, source, tests, and a README
* each repository carries self-contained formatting, linting, and typing
  configuration
* each repository should gain CI, pre-commit, cleanup, and contributor
  guidance before it is advertised as an independent project
* each repository must state whether it is generated from the canonical
  monorepo and where contributors should open issues and pull requests

Do not move routine development to the split repositories until there is a
clear maintenance reason to do so.

Autonomous split-repository development is deferred until at least one of the
following conditions is true:

* a plugin has a separate maintainer
* a plugin needs an independent release cadence
* a plugin needs materially different CI or dependency policy
* external contributors repeatedly need to work on one plugin without touching
  the monorepo
* the core plugin API is stable enough that lockstep changes are rare

## Consequences

The monorepo remains the single place for cross-package refactors, API changes,
and coordinated release preparation.

The export process remains part of the release system and must stay
deterministic. Generated repositories are release artifacts with Git history,
not independent sources of architectural truth.

This reduces short-term operational overhead and avoids splitting contribution
flow before the package ecosystem is stable. It also means generated
repositories need clear notices to prevent contributors from opening changes
against the wrong source of truth.

If a first-party package later becomes independently maintained, the project
can promote that generated repository into an autonomous source repository
without changing the package boundary already established by `ADR-012` and
`ADR-013`.
