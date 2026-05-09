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

## `scripts/run_with_repo_python.sh`

Resolve the repository Python interpreter deterministically and execute Python
arguments through it.

## `scripts/run_repo_tool.py`

Run Python-facing repository tools with cache and temporary state redirected
outside the checkout. Use this helper instead of hand-setting tool cache or
temporary directories under the repository.

## `scripts/validate_repo.py`

Run the standard local validation sequence through `scripts/run_repo_tool.py`.
This is the preferred one-command validation entry point for local changes.

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

Prefetch or verify the local sentence-transformers model artifact required by
the real semantic embedding backend.

Normal CLI indexing now provisions the model automatically on first use. This
script remains available when operators want to pre-warm the cache explicitly.

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

Discovery index state is not stored under `--artifact-root`. Only selector
provenance is persisted under
`.artifacts/benchmarks/<run-id>/selection/*.json`, and the resolved or skipped
commands are also recorded in `campaign-plan.json`.

Example:

```bash
python scripts/benchmark_campaign.py benchmarks.json --dry-run
python scripts/benchmark_campaign.py benchmarks.json --runs 10
```

See `docs/process/performance-benchmarking.md` for the manifest format,
artifact layout, and plugin metadata requirements.

## `scripts/benchmark_release.py`

Run the release-oriented Hyperfine benchmark plan for `codira index --full`,
`codira ctx --json`, and `codira audit --json`.

The default result file is
`.artifacts/benchmarks/release-hyperfine.json`. Use `--dry-run` to inspect the
exact Hyperfine invocation before measuring.

## `scripts/release_audit.sh`

Run conservative release-readiness checks for the current branch and repository
state.

## `scripts/release_rel.sh`

Run the guarded release push path used by `git rel`.

## `scripts/tag_guard.sh`

Validate that a proposed release tag matches the expected `vX.Y.Z` pattern.

## `scripts/changelog_guard.sh`

Validate that `CHANGELOG.md` is structurally consistent with the latest
reachable release tag.

## `scripts/release_system_selfcheck.sh`

Run a read-only consistency check of the installed local release tooling.

## `scripts/ri_fix.py`

Repository helper for local maintenance tasks used during development.

Review the script directly before use if you need exact behavior for a given
operation.
