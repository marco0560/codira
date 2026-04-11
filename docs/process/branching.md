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
