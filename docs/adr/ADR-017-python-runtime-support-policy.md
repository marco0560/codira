# ADR-017 — Python Runtime Support Policy

**Date:** 24/04/2026
**Status:** Superseded in part by ADR-028

## Context

The core project and first-party package projects declare Python 3.13 as the
minimum supported runtime.

Evidence:

- `pyproject.toml` declares `requires-python = ">=3.13"`.
- `.github/workflows/ci.yml` runs CI with `python-version: "3.13"`.
- First-party package `pyproject.toml` files under `packages/` also declare
  `requires-python = ">=3.13"`.

Without an explicit decision, the Python floor is a hidden compatibility
assumption encoded only in packaging and CI configuration.

## Decision

Treat Python 3.13 or newer as the supported **Codira host runtime** for the
current repository state and first-party package set.

All packaging metadata, CI configuration, contributor setup, and release
validation must remain aligned with that runtime floor until a future ADR
changes it.

Support for Python versions older than 3.13 is not part of the current host
runtime compatibility contract. It is not a statement about the Python source
versions that Codira can analyze. ADR-028 defines that separate target-source
contract and supersedes the former conflated interpretation of this decision.

## Consequences

### Positive

- Packaging and CI express one runtime contract.
- Contributors do not need to infer support for older Python versions.
- First-party package metadata stays aligned with the core package.

### Negative

- Users on older Python versions must upgrade before installing supported
  builds.
- Compatibility broadening requires an explicit decision and validation work.

### Neutral / Trade-offs

- The policy documents the current repository contract; it does not prove that
  every dependency ecosystem supports older runtimes.
