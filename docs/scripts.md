# Scripts

## `scripts/bootstrap_dev_environment.py`

Create `.venv`, install development and documentation dependencies, install
repo-local Git configuration, install the extracted first-party analyzer and
backend packages, and optionally run the validation surface.

## `scripts/install_first_party_packages.py`

Install the repository-local first-party analyzer/backend package set from one
authoritative package list shared by bootstrap and CI.

## `scripts/install_repo_git_config.py`

Install the repo-local Git configuration expected by this repository,
including hooks, commit template, and sanctioned aliases.

## `scripts/run_with_repo_python.sh`

Resolve the repository Python interpreter deterministically and execute Python
arguments through it.

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
