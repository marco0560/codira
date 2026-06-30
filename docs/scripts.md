# Scripts

## `scripts/bootstrap_dev_environment.py`

Synchronize the uv-managed `.venv`, install repo-local Git configuration,
install the extracted first-party analyzer and backend packages, and
optionally run the validation surface.

## `scripts/install_first_party_packages.py`

Install the repository-local first-party analyzer/backend package set from one
authoritative package list shared by bootstrap and CI.

## `scripts/install_repo_git_config.py`

Install the repo-local Git configuration expected by this repository,
including hooks, commit template, and sanctioned aliases.

The installer mirrors repository-local aliases only. It does not configure
`user.name`, `user.email`, remote URLs, tokens, or credential helpers. Aliases
that contact GitHub use the operator's own Git or `gh` authentication.

## `scripts/run_with_repo_python.py`

Resolve the repository Python interpreter deterministically and execute Python
arguments through it.

## `scripts/run_repo_tool.py`

Run Python-facing repository tools with cache and temporary state redirected
outside the checkout. Use this helper instead of hand-setting tool cache or
temporary directories under the repository.

## `scripts/validate_repo.py`

Run the standard local validation sequence through `scripts/run_repo_tool.py`.
This is the preferred one-command validation entry point for local changes.
Use `--dry-run` to print the delegated commands without executing them. Use
`--semgrep-complete` to append a broad Semgrep registry scan and save its JSON
report under `.artifacts/analysis/semgrep/`.

## `scripts/check_commit_messages.py`

Validate commit headers for semantic-release compatibility.

This script is used by the GitHub commit-message workflow and enforces the
repository's conventional-commit contract.

## `scripts/clean_repo.py`

Clean ignored repository artifacts using Git as the source of truth rather than
custom filesystem heuristics.

## `scripts/new_decision.py`

Create a new ADR file under `docs/adr/` and append it to the ADR index.

## `scripts/provision_embedding_model.py`

Prefetch or verify the local model artifact required by the active embedding
engine.

Normal CLI indexing now provisions the model automatically on first use. This
script remains available when operators want to pre-warm the cache explicitly.

## `scripts/embedding_model_manifest.py`

Validate and inspect the committed embedding model candidate manifest:

```bash
uv run python scripts/embedding_model_manifest.py --list
uv run python scripts/embedding_model_manifest.py \
  --id bge-small-en-v1.5-onnx \
  --print-config
```

The script does not download model weights. It renders repository configuration
snippets for the selected embedding engine/model entry.

## `scripts/download_embedding_model.py`

Download and smoke-test model artifacts named in
`benchmarks/embedding-model-candidates.json`:

```bash
uv run python scripts/download_embedding_model.py \
  --manifest benchmarks/embedding-model-candidates.json
```

The script sources `$HOME/.hf_token` in a Bash subprocess and reads the
resulting `HF_TOKEN` environment variable. This keeps the token value in one
operator-owned file and avoids copying it into commands.

For ONNX entries, the script downloads `onnx/model.onnx` and `tokenizer.json`
from Hugging Face, installs them under the manifest's `.codira/models/...`
paths, and smoke-tests the artifacts with the first-party ONNX engine. For
SentenceTransformers entries, it downloads the model snapshot into the
Hugging Face cache and runs a local smoke encode.

Select one candidate with `--model-id`:

```bash
uv run python scripts/download_embedding_model.py \
  --model-id bge-small-en-v1.5-onnx
```

## `scripts/compare_embedding_engines.py`

Compare two embedding model manifest entries on a fixed local corpus and report
whether their vectors are compatible enough to justify experimental mixed
engine use:

```bash
uv run python scripts/compare_embedding_engines.py \
  --left bge-small-en-v1.5-sentence-transformers \
  --right bge-small-en-v1.5-onnx
```

The script is read-only. It does not modify indexes or configuration. It emits
a human-readable summary plus JSON by default; use `--json` for JSON only. A
non-zero exit status means the compared engines failed at least one gate:
matching model identity, matching dimensions, or minimum cosine similarity.

## `scripts/run_split_embedding_engine_experiment.py`

Run an experimental split-engine check where indexing uses a
SentenceTransformers manifest entry and query-time `emb`/`ctx` use the paired
ONNX manifest entry:

```bash
uv run python -m scripts.run_split_embedding_engine_experiment \
  --pair-manifest benchmarks/split-embedding-engine-pairs.json \
  --model-manifest benchmarks/embedding-model-candidates.json \
  --repo-manifest benchmarks/uv-backed-repos.local.json \
  --backend sqlite
```

The script first runs `scripts/compare_embedding_engines.py` logic as a
compatibility gate. If the gate passes, it indexes with the
SentenceTransformers config, creates an experimental vector-store identity
alias for the ONNX engine over the same materialized vectors, then runs `emb`
and `ctx` with the ONNX config. Artifacts and JSONL results are written under
`.artifacts/split-embedding-engine-experiment/<timestamp>/`.

This is deliberately not production behavior. Codira's normal vector-store
identity includes the embedding engine, so simply switching config from
SentenceTransformers to ONNX after indexing will not reuse vectors without the
script's explicit experimental aliasing step.

## `scripts/run_onnx_parameter_sweep.py`

Run isolated ONNX Runtime parameter experiments from
`benchmarks/onnx-parameter-sweep.json`:

```bash
uv run python -m scripts.run_onnx_parameter_sweep \
  --sweep-manifest benchmarks/onnx-parameter-sweep.json \
  --model-manifest benchmarks/embedding-model-candidates.json \
  --repo-manifest benchmarks/uv-backed-repos.local.json \
  --backend sqlite
```

Each variant writes a generated config under the sweep artifact directory,
passes it to Codira with `--config-file`, runs an isolated `codira index`, then
times `emb` and `ctx` queries. Results are written under
`.artifacts/onnx-parameter-sweep/<timestamp>/`. Use `--sweep-id` or
`--variant-id` to narrow a run while tuning `batch_size`, `max_tokens`,
`intra_op_num_threads`, `inter_op_num_threads`, and optional
`max_text_chars`.

## `scripts/embedding_engine_matrix_plan.py`

Build a deterministic dry-run JSON plan for the long embedding engine/model
matrix:

```bash
uv run python scripts/embedding_engine_matrix_plan.py
```

The plan combines `benchmarks/embedding-engine-matrix.json` with the embedding
model candidate manifest and the selected repository benchmark manifest. It is
safe to run before the long campaign because it only validates manifests and
prints planned runs.

## `scripts/run_final_embedding_model_campaign.py`

Run the final engine/model measuring campaign:

```bash
uv run python -m scripts.run_final_embedding_model_campaign \
  --manifest benchmarks/uv-backed-repos.local.json \
  --model-manifest benchmarks/embedding-model-candidates.json \
  --backend duckdb \
  --runs 5 \
  --warmup 1
```

The wrapper writes artifacts under
`.artifacts/final-embedding-model-campaign/<timestamp>/`, first runs
`scripts/download_embedding_model.py` against the model manifest, records the
optional baseline path and manifests, writes one generated config per
model/backend under the artifact directory, and passes that config to benchmark
commands with `--config-file`. It does not rewrite repository
`.codira/config.toml` files. Use `--baseline PATH` only to record which
previous matrix should be used later during analysis. Use
`--preflight-only` to stop after download and smoke tests. Use `--backend both`
only when the campaign must run separate SQLite and DuckDB backend phases for
each model/repository pair as well as PyTorch and ONNX Runtime embedding
engines.

The wrapper applies conservative benchmark defaults for large embedding models:
768-dimensional candidates use `batch_size = 1`,
`[embeddings.indexing].max_text_chars = 2000`, Torch threads `4/1`, and ONNX
thread limits `intra_op_num_threads = 4` plus `inter_op_num_threads = 1`.
384-dimensional ONNX candidates use `batch_size = 8`; 384-dimensional
SentenceTransformers candidates use `batch_size = 32`.

## `scripts/benchmark_index.py`

Run one instrumented index pass and emit structured JSON with phase timings,
embedding batch sizes, and index summary counters.

Use this script when evaluating indexing regressions or tuning embedding batch
and Torch runtime settings.

When `--output` is supplied, the JSON artifact is written to that path and
includes run metadata: UTC timestamp, Codira version, Git commit, active plugin
inventory, and profiler/tool availability.

## `scripts/benchmark_campaign.py`

Run a manifest-driven performance measurement campaign across repository size
categories.

The campaign runner builds phase-timing, Hyperfine, cProfile, and optional
Pyinstrument command plans for each configured repository. Use `--dry-run` to
write and inspect `.artifacts/benchmarks/<run-id>/campaign-plan.json` without
executing benchmark commands. `--dry-run` still validates the manifest before
printing the plan. The dry run still performs the adaptive discovery pass used
to resolve repo-specific benchmark commands.

Use `--continue-on-error` for torture campaigns. In that mode every planned
command is attempted, command stdout and stderr are retained under
`<run-id>/logs/`, and failures are summarized in
`<run-id>/failure-summary.json`.

The manifest supports optional repository-local `commands` entries that extend
the Hyperfine command set beyond the default `index --full`, warm `index`, and
`ctx --json` measurements. Each command is written as a JSON argv array
excluding the `codira` executable itself, for example:

```json
["sym", "build_parser", "--json"]
```

Supported manifest-benchmark subcommands are:

- `help`
- `index`
- `cov`
- `sym`
- `symlist`
- `emb`
- `calls`
- `refs`
- `audit`
- `ctx`
- `plugins`
- `caps`

Manifest command tokens may use `{path}`, `{output_dir}`, and `{query}`
placeholders. For path-aware subcommands, the campaign runner appends
`--path` and `--output-dir` automatically when they are omitted.

Before building the final Hyperfine command matrix, the campaign runs an
adaptive discovery pass for each repository:

- a temporary Codira index is built under `/tmp`
- `symlist --json` is used to discover candidate symbols with meaningful graph
  connectivity
- semantic query candidates are ranked from the manifest query plus discovered
  symbol and module names
- adaptive commands such as `sym`, `calls`, `refs`, `emb`, `ctx`, and
  `symlist` are resolved to repo-specific commands with more significant output
- unresolved adaptive commands are skipped instead of aborting the whole repo
  campaign

Discovery index state is not stored under `--artifact-root`. Selector
provenance is persisted under
`.artifacts/benchmarks/<run-id>/selection/*.json`, discovery command output is
persisted under `.artifacts/benchmarks/<run-id>/logs/discovery/`, and the
resolved or skipped commands are also recorded in `campaign-plan.json`.

Example:

```bash
python scripts/benchmark_campaign.py benchmarks.json --dry-run
python scripts/benchmark_campaign.py benchmarks.json --runs 10
```

## `scripts/run_manifest_baseline.py`

Run the paired SQLite and DuckDB `benchmarks/bk-cpp.local.json` torture
baseline with fixed runtime environment defaults, `--artifact-root .artifacts`,
and `--continue-on-error`.

```bash
uv run python -m scripts.run_manifest_baseline --runs 5 --warmup 1
```

See `docs/process/performance-benchmarking.md` for the manifest format,
artifact layout, and plugin metadata requirements.

## `scripts/benchmark_release.py`

Run the release-oriented Hyperfine benchmark plan for `codira index --full`,
`codira ctx --json`, and `codira audit --json`.

The default result file is
`.artifacts/benchmarks/release-hyperfine.json`. Use `--dry-run` to inspect the
exact Hyperfine invocation before measuring.

## `scripts/release_audit.py`

Run conservative release-readiness checks for the current branch and repository
state.

## `scripts/release_rel.py`

Run the guarded release push path used by `git rel`.

## `scripts/tag_guard.py`

Validate that a proposed release tag matches the expected `vX.Y.Z` pattern.

## `scripts/changelog_guard.py`

Validate that `CHANGELOG.md` is structurally consistent with the latest
reachable release tag.

## `scripts/release_system_selfcheck.py`

Run a read-only consistency check of the installed local release tooling.

## `scripts/ri_fix.py`

Repository helper for local maintenance tasks used during development.

Review the script directly before use if you need exact behavior for a given
operation.
