# Getting Started

## Install the published package

For normal use, install Codira from PyPI into the virtual environment of the
repository you want to analyze. This is the simplest path when you only need to
use `codira` and do not need unreleased plugins or features:

```bash
source .venv/bin/activate
pip install codira-bundle-official
```

That installs `codira`, the first-party analyzer plugins and backends.

The analyzers currently available are:

- Python
- C
- C++
- JSON
- Bash
- Markdown
- Text

the last two being used to analyze doccumentation, while the backend plugins are:

- SQLite
- DuckDB

Prefer this published install path over an editable checkout unless you are
developing Codira itself, testing unreleased first-party plugins, or validating
changes from a development branch.

Verify the install:

```bash
codira -V
codira plugins
```

For a core-only install:

```bash
pip install codira
```

The core-only package installs the CLI and core contracts, but it does not
install the official first-party analyzer/backend bundle. Use
`codira-bundle-official` for a ready-to-use end-user installation.

## Bootstrap this repository

Create the local development environment cloning from github and install the
repo-local Git configuration:

```bash
git clone https://github.com/marco0560/codira
python3 scripts/bootstrap_dev_environment.py
```

The bootstrap script installs the core package, the extracted first-party
analyzer/backend packages, and the local embedding dependencies through the
uv-managed repository environment.

The repository-local first-party package set is owned by:

```bash
uv run python scripts/install_first_party_packages.py \
  --include-core \
  --core-extra docs \
  --core-extra semantic
```

Developer automation is uv-based for dependency resolution and lockfile
maintenance, while the actual checks run from the uv-managed `.venv` against
the editable first-party package set.

## Install into another repository

Use this source-tree install path only when you want the target repository to
run against this checkout, for example while developing Codira, testing
bleeding-edge plugins, or validating unreleased features.

Example:

```bash
source .venv/bin/activate
uv run python ../codira/scripts/install_first_party_packages.py \
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
uv run python ../codira/scripts/provision_embedding_model.py
```

## Initialize Codira in a repository

Codira can run without a repository config file. If no explicit config exists,
runtime commands use built-in defaults and create a default user-level config
on first use when the platform user config directory is writable.

For a project-local setup, create a repository config:

```bash
codira config init --level repo
```

This writes `.codira/config.toml`. The config file may be committed when the
repository should share analyzer selection, backend choice, or plugin settings.
Normal `.codira` index artifacts remain local cache data and should stay
ignored.

To generate the full first-party plugin configuration surface:

```bash
codira config init --level repo --full
```

Inspect and validate the effective configuration:

```bash
codira config dump
codira config validate
codira config explain embeddings.batch_size
```

Effective configuration is resolved in this order:

```text
CLI flags
-> CODIRA_* environment variables
-> repository config: .codira/config.toml
-> user config
-> system config
-> built-in defaults
```

## Tune embedding runtime

`codira` computes semantic embeddings through the local sentence-transformers
backend during indexing. The default settings are deterministic, and can be
made explicit in the repository config when a project needs repeatable runtime
tuning.

Inspect the effective config:

```bash
codira config dump
codira config explain embeddings.batch_size
```

Create an explicit profile:

```bash
codira config init --profile low-memory
codira config init --level repo --profile gpu
```

Operators can still tune one process with environment variables. These values
override config files:

| Variable | Meaning |
| --- | --- |
| `CODIRA_EMBED_BATCH_SIZE` | Batch size passed to the sentence-transformers `encode` call. Larger batches can improve full-index throughput when memory is sufficient. |
| `CODIRA_EMBED_DEVICE` | Device string passed to sentence-transformers. The default is `cpu`; use another value only when the local PyTorch and model environment supports it. |
| `CODIRA_TORCH_NUM_THREADS` | Optional intra-op PyTorch thread count, applied with `torch.set_num_threads`. This controls CPU parallelism inside individual Torch operations. |
| `CODIRA_TORCH_NUM_INTEROP_THREADS` | Optional inter-op PyTorch thread count, applied with `torch.set_num_interop_threads`. This controls scheduling parallelism across independent Torch operations. |

Unset `CODIRA_TORCH_*` values leave PyTorch defaults unchanged. Invalid integer
values fail fast before embedding inference. These variables change runtime
scheduling only; they do not change indexed symbols, embedding payloads, or
query semantics.

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
uv run python scripts/validate_repo.py
```

Run Python-facing tools through `scripts/validate_repo.py` or
`scripts/run_repo_tool.py` so tool cache and temporary state stays outside the
repository cleanup surface.
