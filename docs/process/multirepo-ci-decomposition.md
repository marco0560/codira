# Multirepo CI Decomposition

## Purpose

This note records the CI contract each future repository should carry after the
Phase 3 split.

It is intentionally narrower than the current monorepo `CI` workflow. The goal
is to make the post-split repository jobs explicit before files move, so the
split does not invent CI behavior package by package.

## Source Of Truth

The executable source of truth for this decomposition is:

* `scripts/future_repo_ci.py`

The regression coverage for that contract lives in:

* `tests/test_future_repo_ci.py`

## Core Repository

Repository:

* `codira`

Purpose:

* contracts
* registry/discovery
* CLI orchestration
* shared indexing/query/storage layers
* cross-package integration validation

Install commands:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev,docs,semantic]"
```

Validation commands:

```bash
python -m pre_commit run --all-files
python -m black --check src scripts tests
python -m ruff check src scripts tests
python -m mypy src scripts tests
python -m pytest -q
```

Notes:

* The core repo keeps the installed-wheel integration test that verifies plugin
  discovery without sibling-source loading.
* The core repo no longer owns package-local metadata assertions that have
  moved under `packages/*/tests`.

## Package Repositories

Repositories:

* `codira-analyzer-python`
* `codira-analyzer-json`
* `codira-analyzer-c`
* `codira-analyzer-bash`
* `codira-backend-sqlite`

Install command:

```bash
python -m pip install -e ".[test]"
```

Validation commands:

```bash
python -m black --check src tests
python -m ruff check src tests
python -m mypy src tests
python -m pytest -q tests
```

Notes:

* Each package now has package-local tests under its own `tests/` directory.
* Package-local README verification snippets already point at those test paths.
* Before the first publish, local split-repo rehearsal should install the
  current core checkout explicitly rather than resolving `codira` from an
  index. Use `scripts/verify_exported_split_repos.py` from the monorepo for
  that pre-publish validation pass.

## Bundle Repository

Repository:

* `codira-bundle-official`

Install command:

```bash
python -m pip install -e ".[test]"
```

Validation commands:

```bash
python -m black --check tests
python -m ruff check tests
python -m mypy tests
python -m pytest -q tests
```

Notes:

* The bundle repo is metadata-heavy and does not own a `src/` tree.
* The package-local test remains focused on dependency metadata integrity.
* Before publication, bundle rehearsal also needs the local first-party package
  repos installed explicitly. Use `scripts/verify_exported_split_repos.py`
  rather than a plain `pip install -e ".[test]"` from a clean environment.
