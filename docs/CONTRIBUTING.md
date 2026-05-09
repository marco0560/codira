# Contributing

## Source of truth

The repository filesystem is the source of truth. Do not assume structures,
modules, or workflows that are not present in the repo.

## Validation

Run the standard local validation loop before concluding a change:

```bash
uv run python scripts/validate_repo.py
```

Run Python-facing tools through `scripts/validate_repo.py` or
`scripts/run_repo_tool.py` so tool cache and temporary state stays outside the
repository cleanup surface. Do not point pre-commit, ruff, pytest, or process
temporary directories at repository-local paths.

CI and the pre-push hook also run broader repository checks such as
`mypy .`, which includes the first-party packages under `packages/`.

The repository uses uv for dependency resolution and lockfile maintenance.
The validation commands themselves run from the uv-managed `.venv` against the
editable core and first-party package set, so local checks match the
installed-package layout used by CI.

## Bootstrap

A fresh clone can be initialized with:

```bash
python3 scripts/bootstrap_dev_environment.py
```

That bootstrap flow creates `.venv`, installs development and documentation
dependencies, installs the repository-local first-party package set, and
installs repo-local Git configuration.

## Release discipline

Before pushing release-bearing changes to `main`, run:

```bash
git release-audit
```

The local release contract is documented in `docs/release/checklist.md` and
`docs/release/process.md`.

## Branching and decisions

Repository branch and ADR workflow guidance is documented in:

- `docs/process/branching.md`
- `docs/process/decisions.md`

## Context exploration

Before broad patching work:

```bash
codira ctx "<query>" --json
```

Use `rg` first when you need to verify candidate symbols or files.

## Architectural work

ADR-driven architecture changes should be linked to the corresponding
documentation under `docs/adr/`.

The accepted migration direction for pluggable backends and analyzers is
documented in `ADR-004` and is now the implemented branch architecture.

When architecture changes land, update all three surfaces together:

- `docs/architecture/` for the stable current-state description
- `docs/adr/` for durable decision and migration records
- `README.md` when user-facing capability or workflow descriptions change

For analyzer or scanner changes, validate behavior against a real Git-backed
repository when practical, not only against synthetic fixtures.
