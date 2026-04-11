# ADR-009 — End-user distribution and publishing model

**Date:** 03/04/2026
**Status:** Accepted

## Context

`ADR-007` established the first-party package boundary for extracted optional
plugins and accepted `codira[bundle-official]` as the umbrella install
contract.

That decision is structurally sound, but it leaves one practical packaging
question open: what should an end user install, and what release model makes
that install work without requiring monorepo-specific knowledge?

The current repository contains four relevant distributions:

* `codira`
* `codira-analyzer-c`
* `codira-analyzer-bash`
* `codira-bundle-official`

The repository also serves two different audiences:

* end users, who want one install command and do not care about the monorepo
  layout
* repository contributors, who may use editable installs from local paths

Those audiences should not be forced through the same workflow.

Additional constraints now shape the decision:

* the root package already uses SCM-managed versioning
* the analyzer and bundle packages currently use manually managed versions
* the repository remains a monorepo for now
* independent analyzer SCM versioning inside the monorepo would add release
  complexity without clear user benefit

## Decision

Adopt a two-surface distribution model:

* `codira-bundle-official` becomes the primary end-user install target
* `codira[bundle-official]` remains a compatible umbrella surface on the
  core package

### End-user install target

The primary end-user command is:

```bash
pip install codira-bundle-official
```

This package acts as the curated umbrella distribution for the official
repository-owned capabilities.

Its responsibility is to depend on:

* `codira`
* `codira-analyzer-c`
* `codira-analyzer-bash`
* the semantic embedding stack required by the curated official bundle

### Core extra remains valid

The `bundle-official` extra on `codira` remains supported as an equivalent
install contract:

```bash
pip install "codira[bundle-official]"
```

This preserves continuity with `ADR-007` and allows users who prefer extras to
keep using that interface.

### Publish all first-party distributions to a package index

The seamless end-user experience depends on normal package-name resolution.

Therefore the following distributions must be published to a package index such
as PyPI:

* `codira`
* `codira-analyzer-c`
* `codira-analyzer-bash`
* `codira-bundle-official`

The monorepo directory structure alone is not sufficient for `pip` to resolve
dependency names during a normal install.

### Contributor workflow stays monorepo-aware

Repository contributors may continue to install packages from local paths under
`packages/` during editable development.

That workflow is explicitly a contributor workflow, not the documented
end-user install path.

### Version policy while the repository stays a monorepo

While the analyzers and bundle remain in the monorepo:

* `codira` continues to use SCM-managed versioning
* `codira-analyzer-c` keeps a manually managed version
* `codira-analyzer-bash` keeps a manually managed version
* `codira-bundle-official` keeps a manually managed version

Independent SCM-managed analyzer versioning is deferred until each analyzer
has its own repository and therefore its own tag stream.

## Consequences

### Positive

* end users get a simple install command without needing to understand extras
  syntax or local package paths
* the published bundle package provides a stable "ring to rule them all"
  surface for official capabilities
* contributor workflows remain flexible without leaking monorepo details into
  end-user documentation
* package publishing can proceed incrementally without forcing premature
  repository splits

### Negative

* release operations must publish multiple distributions instead of only one
* package versions across the monorepo are not all derived from the same SCM
  policy
* documentation must now explain both the end-user bundle package and the core
  extra compatibility surface

### Neutral / Trade-offs

* `codira[bundle-official]` remains valid, but it is no longer the primary
  user-facing recommendation
* manual analyzer and bundle versions are acceptable while the monorepo
  structure remains intact
* future repository splits may later justify moving analyzer packages to
  SCM-managed versioning independently

## Operational Rules

* Document `codira-bundle-official` as the default install target for
  end users.
* Keep `codira[bundle-official]` working as a compatibility surface.
* Publish plugin distributions before or together with root releases that
  depend on them.
* Revisit analyzer version management only when repository splits become real,
  not while the monorepo remains the source of truth.
