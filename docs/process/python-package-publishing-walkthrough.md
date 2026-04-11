# Python Package Publishing Walkthrough

## Purpose

This note records the maintainer workflow for publishing `codira` and its
first-party plugin packages so end users can install the official bundle
through standard `pip` package-name resolution.

## Audience

This document is for maintainers, not end users.

End users should only need the documented install command, while maintainers
need to understand what `pip` resolves, what must be published, and what order
to publish packages in.

## Packaging Model

The `v2.0.0` publish is a coordinated multirepo release train. The current
monorepo remains the staging source for the split, but the final PyPI upload
must be built from the split repositories, not from a transitional monorepo
checkout.

The final repository set contains these installable distributions:

* `codira`
* `codira-analyzer-python`
* `codira-analyzer-json`
* `codira-analyzer-c`
* `codira-analyzer-bash`
* `codira-backend-sqlite`
* `codira-bundle-official`

The intended end-user install target is:

```bash
pip install codira-bundle-official
```

The compatible extra-based surface remains:

```bash
pip install "codira[bundle-official]"
```

## How `pip` Resolves Package Names

When `pip` sees a dependency such as:

* `codira-analyzer-c`
* `codira-analyzer-bash`
* `sentence-transformers>=3.0`

it does not inspect arbitrary subdirectories in a Git checkout.

Instead it:

1. reads dependency metadata from the package being installed
2. asks the configured package index for each dependency name
3. downloads a wheel or source distribution for each resolved package

That means a monorepo layout such as `packages/codira-analyzer-c/` is not
enough by itself for normal end-user installation. For `pip` to resolve those
names seamlessly, the packages must be published to a package index or
installed explicitly by path.

## What Must Be Published

For the official bundle experience to work without local-path knowledge,
publish at least:

* `codira`
* `codira-analyzer-python`
* `codira-analyzer-json`
* `codira-analyzer-c`
* `codira-analyzer-bash`
* `codira-backend-sqlite`
* `codira-bundle-official`

The bundle package is the primary end-user target. The root extra remains a
compatible secondary surface.

## Version Policy

The initial `v2.0.0` publish is coordinated:

* every first-party distribution publishes `2.0.0`
* `codira-bundle-official` pins the matching `2.0.0` package set
* release notes are coordinated across repositories
* artifacts are built from the split repositories

After the initial `2.0.0` train, split repositories may evolve independently.
Repository-local tags become the source of truth for future package versions.

## Build Concepts

### Wheel

A wheel (`.whl`) is the standard built Python package format.

It is a ready-to-install archive that lets `pip` install a package without
running a full build step on the user's machine.

### Source Distribution

A source distribution (`.tar.gz`) contains the source package and requires a
local build step during installation.

For end-user experience, wheels are preferred whenever possible.

## Required Accounts And Tools

Create accounts on:

* PyPI
* TestPyPI

Install local release tools in a dedicated environment:

```bash
python -m venv .venv-release
source .venv-release/bin/activate
python -m pip install --upgrade pip build twine
```

## Preflight Checks

Before publishing:

1. verify package names are available on PyPI
2. verify versions are the intended release versions
3. build every distribution
4. run `twine check` on every generated artifact

## Split-First Release Gate

Before building release artifacts:

1. export the accepted repository set from the monorepo split manifest
2. create or update the real split repositories from those exports
3. remove monorepo-only package paths from the final core repository
4. ensure every split repository builds and tests in isolation
5. ensure the core repository keeps installed-package integration coverage
6. tag each repository for the coordinated `v2.0.0` release

Do not publish `v2.0.0` directly from the monorepo staging checkout.

## Build Steps

From each split repository root:

Build `codira`:

```bash
python -m build
```

Build `codira-analyzer-c`:

```bash
python -m build
```

Build `codira-analyzer-python`:

```bash
python -m build
```

Build `codira-analyzer-json`:

```bash
python -m build
```

Build `codira-analyzer-bash`:

```bash
python -m build
```

Build `codira-backend-sqlite`:

```bash
python -m build
```

Build `codira-bundle-official`:

```bash
python -m build
```

## Artifact Validation

Validate built artifacts before upload:

```bash
python -m twine check dist/*
```

## Recommended Release Order

Publish in this order:

1. `codira-analyzer-python`
2. `codira-analyzer-json`
3. `codira-analyzer-c`
4. `codira-analyzer-bash`
5. `codira-backend-sqlite`
6. `codira`
7. `codira-bundle-official`

This ensures that when the root package or bundle resolves dependency names,
the analyzer distributions already exist in the package index.

## TestPyPI Rehearsal

Upload to TestPyPI first:

```bash
python -m twine upload --repository testpypi dist/*
```

Then test installation from a fresh environment:

```bash
python -m venv /tmp/ri-test
source /tmp/ri-test/bin/activate
pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  codira-bundle-official
codira plugins
```

The extra PyPI index is needed because TestPyPI typically does not host common
third-party dependencies such as `sentence-transformers`.

## Production Upload

Once TestPyPI works, upload to PyPI:

```bash
python -m twine upload dist/*
```

## Final End-User Verification

In a fresh environment:

```bash
python -m venv /tmp/ri-prod
source /tmp/ri-prod/bin/activate
pip install codira-bundle-official
codira plugins
```

Verify that the expected official analyzers and the SQLite backend are discoverable.

## Operational Notes

* Use API tokens instead of account passwords for upload.
* Once a version is published on PyPI, that exact version cannot be replaced
  with different contents.
* Treat editable local installs under `packages/` as monorepo staging workflow,
  not as end-user documentation.
* Publish in the recommended package order across repositories.
* Use one final TestPyPI smoke test for the bundle after every repository has
  uploaded its `2.0.0` artifacts.
