# Multirepo Split Manifest

## Purpose

This note records the path-level ownership manifest for the accepted future
repositories.

The goal is to make the actual repository extraction step mechanical:

* which paths move into each future repository
* which relevant compatibility or integration paths still stay in core

## Source Of Truth

The executable source of truth for this manifest is:

* `scripts/future_repo_split_manifest.py`

The regression coverage for that contract lives in:

* `tests/test_future_repo_split_manifest.py`

The mechanical export helper for rehearsing one future repository from that
manifest lives in:

* `scripts/future_repo_export.py`

The regression coverage for the export helper lives in:

* `tests/test_future_repo_export.py`

## Core Repository

Repository:

* `codira`

Owned paths:

* `.gitignore`
* `.github/workflows/`
* `.pre-commit-config.yaml`
* `.releaserc.json`
* `CHANGELOG.md`
* `LICENSE`
* `README.md`
* `docs/`
* `examples/`
* `mkdocs.yml`
* `package-lock.json`
* `package.json`
* `pyproject.toml`
* `scripts/`
* `src/codira/`
* `tests/`

Notes:

* The core repository retains the installed-wheel integration tests.
* The core repository retains the compatibility surfaces until `#13` removes
  them after the split.
* The core repository also retains the root files required by its kept CI,
  docs, and release workflows.

## Analyzer Repositories

Repositories:

* `codira-analyzer-python`
* `codira-analyzer-json`
* `codira-analyzer-c`
* `codira-analyzer-bash`

Owned paths per repository:

* `README.md`
* `pyproject.toml`
* `src/`
* `tests/`

Core paths that still matter operationally after the split:

* `src/codira/analyzers/python.py`
* `src/codira/analyzers/json.py`
* `src/codira/analyzers/c.py`
* `src/codira/analyzers/bash.py`
* `tests/test_plugins.py`

These paths stay in core because they either provide compatibility imports or
core-side integration coverage.

## Backend Repository

Repository:

* `codira-backend-sqlite`

Owned paths:

* `README.md`
* `pyproject.toml`
* `src/`
* `tests/`

Core paths that still matter operationally after the split:

* `src/codira/indexer.py`
* `src/codira/sqlite_backend_support.py`
* `tests/test_plugins.py`

## Bundle Repository

Repository:

* `codira-bundle-official`

Owned paths:

* `README.md`
* `pyproject.toml`
* `tests/`

Core paths that still matter operationally after the split:

* `tests/test_plugins.py`

## Use During The Split

During the actual multirepo extraction:

1. copy the owned paths into the target repository
2. keep the listed core paths in `codira`
3. verify the copied repository against the CI contract in
   `docs/process/multirepo-ci-decomposition.md`
4. only after the repositories exist and validate independently, proceed to
   the `#13` cleanup in core

For split rehearsal from the monorepo checkout, use:

```bash
python scripts/future_repo_export.py codira-analyzer-python
python scripts/future_repo_export.py codira-analyzer-python --destination-root /tmp/codira-split
```
