# ADR-018 — CI Platform Coverage Policy

**Date:** 24/04/2026
**Status:** Accepted

## Context

The repository CI workflow currently validates on one operating-system target.

Evidence:

- `.github/workflows/ci.yml` sets `runs-on: ubuntu-latest`.
- The same workflow installs the project, installs repository git config, runs
  pre-commit, `black --check .`, `ruff check .`, `mypy .`, `pytest`, and
  `bash scripts/release_audit.sh`.

The repository also contains Windows-facing path and shell usage through local
development, but Windows and macOS are not part of the current CI matrix.

## Decision

Treat Linux on GitHub-hosted `ubuntu-latest` runners as the authoritative CI
platform for the current repository state.

Cross-platform support outside that CI platform is not guaranteed unless a
specific test, script, or release procedure explicitly validates it.

Any future expansion to Windows or macOS CI must be made explicitly and must
define the required validation commands for those platforms.

## Consequences

### Positive

- The repository has one deterministic CI baseline.
- Release and contributor validation can refer to the same CI command set.
- Platform support claims remain traceable to actual workflow coverage.

### Negative

- Platform-specific regressions outside Linux may not be caught by CI.
- Windows or macOS behavior must not be claimed as covered without additional
  validation.

### Neutral / Trade-offs

- Local platform checks may still be useful, but they are not the authoritative
  CI contract until represented in workflow configuration.
