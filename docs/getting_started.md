# Getting Started

## Install the published package

For normal use, install the official bundle into the virtual environment of the
repository you want to analyze:

```bash
source .venv/bin/activate
pip install codira-bundle-official
```

That installs `codira`, the first-party Python, JSON, C, and Bash analyzers,
and the first-party SQLite backend.

The package is published on PyPI. If you only need to use `codira`, prefer this
published install path over an editable checkout from a development branch.

Verify the install:

```bash
codira -V
codira plugins
```

For a core-only install:

```bash
pip install codira
```

## Bootstrap this repository

Create the local development environment and install the repo-local Git
configuration:

```bash
python3 scripts/bootstrap_dev_environment.py
```

The bootstrap script installs the core package, the extracted first-party
analyzer/backend packages, and the local embedding dependencies. It also
provisions the local model artifact used by the real embedding backend, so
`codira index` can build persisted embeddings without ad hoc first-run
downloads inside this repository.

The repository-local first-party package set is owned by:

```bash
python scripts/install_first_party_packages.py \
  --include-core \
  --core-extra dev \
  --core-extra docs \
  --core-extra semantic
```

Developer automation is Poetry-based for dependency resolution and lockfile
maintenance, while the actual checks run the installed tools directly from
`.venv` and the editable first-party package set.

## Install into another repository

Install `codira` into the virtual environment of the repository you want to
analyze.

Example:

```bash
source .venv/bin/activate
python ../codira/scripts/install_first_party_packages.py \
  --python "$VIRTUAL_ENV/bin/python" \
  --include-core \
  --core-extra semantic
```

This keeps the `codira` CLI available in the target repository while using
the live source tree from this repository.

The current source-tree install keeps the embedding stack in the core package
while the extracted first-party analyzers and backend are installed from
`packages/`. The published end-user bundle is `codira-bundle-official`; while
working from the current checkout, the canonical local package set is the one
installed by `scripts/install_first_party_packages.py`.

Use `codira plugins` after installation if you want to verify whether a
capability came from the core package, an official extracted package, or a
third-party plugin.

On first indexing run, `codira` provisions the configured local model
artifact automatically if it is missing. If automatic provisioning cannot
complete, the CLI fails with a concise remediation message.

You can still prefetch the model explicitly:

```bash
source .venv/bin/activate
python ../codira/scripts/provision_embedding_model.py
```

## First commands

Build or refresh the repository-local index:

```bash
codira index
```

Inspect exact symbol data:

```bash
codira sym build_parser
codira sym build_parser --json
```

Inspect context retrieval:

```bash
codira ctx "schema migration rules"
codira ctx "missing numpy docstring" --json
```

Inspect bounded graph traversal and optional DOT export:

```bash
codira calls build_parser --tree
codira calls build_parser --tree --dot
codira refs _retrieve_script_candidates --incoming --tree
codira refs _retrieve_script_candidates --incoming --tree --dot
```

## Validation surface

The repository expects contributors to run:

```bash
python scripts/validate_repo.py
```

Run Python-facing tools through `scripts/validate_repo.py` or
`scripts/run_repo_tool.py` so tool cache and temporary state stays outside the
repository cleanup surface.
