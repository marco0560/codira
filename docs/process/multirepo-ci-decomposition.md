# Distribution repository CI contract

The canonical monorepo remains the development source of truth under
[ADR-014](../adr/ADR-014-canonical-monorepo-generated-distribution-repositories.md).
Exports are generated distribution/rehearsal trees; routine source development
stays here. These tools remain maintained compatibility contracts, not a plan
to move development into autonomous repositories.

## Source of truth

`scripts/future_repo_ci.py` declares the command vectors; coverage is in
`tests/test_future_repo_ci.py`. The [export manifest](multirepo-split-manifest.md)
lists the currently declared repository set. This document records that exact
contract, including its qualification limits.

## Core declaration

Install:

```bash
uv sync --frozen --group dev --extra docs --extra semantic
uv run python scripts/install_first_party_packages.py --include-core --core-extra docs --core-extra semantic
```

Validate:

```bash
uv run pre_commit run --all-files
uv run ruff check src scripts tests
uv run ruff format --check src scripts tests
uv run mypy src scripts tests
uv run pytest -q
```

## Package declarations

All declared package repositories except the metadata-only official bundle use:

```bash
uv sync --frozen --extra test
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src tests
uv run pytest -q tests
```

The bundle has no source tree and validates its tests only:

```bash
uv sync --frozen --extra test
uv run ruff check tests
uv run ruff format --check tests
uv run mypy tests
uv run pytest -q tests
```

## Qualification boundary

These command vectors describe the declarative CI contract. The exporter copies
owned paths; it does not synthesize a `uv.lock` or a full autonomous CI/release
system. In particular, `uv sync --frozen` requires an appropriate lockfile;
the package export manifests do not currently declare one. The declarations
alone are not proof that every freshly exported tree can run this CI unchanged.

For pre-publication local-core verification use
`scripts/verify_exported_split_repos.py` from the monorepo. It builds a separate
validation plan against the local core and installs local first-party packages
before validating the bundle. Its inventory comes from
`scripts.first_party_packages`, which is broader than the legacy export
manifest; provide all trees required by the selected verification plan.
Inspect its `--help` and plan before execution. Keep installed-wheel release
qualification under the maintained [release checklist](../release/checklist.md).
