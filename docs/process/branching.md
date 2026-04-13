# Branching

## Purpose

This document defines the repository branching model used for normal
maintenance work and for future architecture work.

## Default branch type

The default working branch for code changes is an issue branch:

```text
issue/<issue-number>-short-description
```

Rules:

- one issue per branch
- merge through pull requests
- keep `main` stable and releasable
- rebase or merge from `main` regularly as needed

When work is not tied to a numbered issue, use a Conventional Commit-style
branch name:

```text
<type>/<short-description>
```

The `<type>` segment should match the repository's commit and CI categories,
such as `fix`, `feat`, `docs`, `chore`, `refactor`, `test`, `ci`, `build`,
`perf`, or `release`. The description should be short, lowercase, and
hyphenated, for example:

```text
chore/quality-hardening-phase-2
```

## Exploratory branches

Exploratory work that is not yet normal issue implementation should use:

```text
spike/<topic>
phase/<name>
```

Rules:

- exploratory branches are allowed to be temporary
- they must not be merged into `main` without an approved decision or a
  corresponding issue
- architectural migrations should use their own dedicated branch

## ADR-004 boundary

The accepted pluggable-backend migration described in `ADR-004` is explicitly
expected to run on its own dedicated branch, not on the repository
standardization branch.

That branch is also expected to carry its own architecture documentation and
ADR updates as the migration progresses, not as a final cleanup after code
lands.
