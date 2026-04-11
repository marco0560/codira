# Issue 011 Optional Plugin Shim Inventory

## Purpose

This note records the remaining compatibility surfaces for the extracted
first-party optional analyzer packages during Phase 1 of the package-boundary
migration.

It exists to record the transitional shim shape that remained during the
monorepo phase and the cleanup target that issue `#13` completes.

## Scope

This inventory covers the extracted first-party optional analyzers only:

- `codira-analyzer-c`
- `codira-analyzer-bash`

It does not cover the future default-implementation extraction planned for
issue `#12`.

## Current Compatibility Surfaces

### `src/codira/analyzers/c.py`

Role:

- preserves historical imports from `codira.analyzers.c`
- attempts to import `codira_analyzer_c`
- raises a deterministic install hint when the extracted package is absent

Status:

- retained as an import-only compatibility shim after `#13`
- must not regain implementation ownership

### `src/codira/analyzers/bash.py`

Role:

- preserves historical imports from `codira.analyzers.bash`
- attempts to import `codira_analyzer_bash`
- raises a deterministic install hint when the extracted package is absent

Status:

- retained as an import-only compatibility shim after `#13`
- must not regain implementation ownership

### `src/codira/analyzers/__init__.py`

Role:

- re-exports core analyzers directly
- conditionally re-exports `CAnalyzer` and `BashAnalyzer` through the shim
  modules when those extracted packages are importable

Status:

- accepted as a narrow package-surface compatibility layer
- should stay lightweight and import-only

### `src/codira/registry.py`

Role:

- treats `codira.analyzers.c` and `codira.analyzers.bash` as optional
  built-in factory import targets
- relies on the shim modules to bridge current monorepo contributor installs to
  extracted first-party analyzer packages

Status:

- retained because it preserves historical import names without restoring
  implementation ownership in core
- no longer depends on monorepo-local bridging after issue `#13`

## Accepted Phase 1 Rule

These shims are allowed only to preserve compatibility imports after the split.

They must remain:

- narrow
- import-only
- deterministic
- explicitly documented as temporary

They must not:

- reintroduce analyzer implementation logic into core
- become the primary discovery mechanism for published installs
- hide missing-package failures without an operator-facing message

## Removal Target

The removal target for these shims remains issue `#13`.

That cleanup should happen only after:

- issue `#11` completes the Phase 1 package-boundary reconciliation
- issue `#12` completes the default-implementation extraction
- the multirepo split removes the need for sibling-source loading

Installed package metadata and entry points are now the only supported
discovery path for the extracted first-party analyzers.
