# Issue #28 Embedding Calibration Execution

## Goal

Add a deterministic hardware-aware embeddings calibration command whose output
is compatible with the Codira configuration system introduced for issue #17.

## Ledger

| Step | Status | Evidence |
| --- | --- | --- |
| Baseline branch and worktree check | Done | `git status --short --branch` showed `feat/issue-17-configuration-system` with only the current phase edits. |
| Capability discovery | Done | `codira caps --json` confirmed `config` support and no existing `calibrate` command. |
| Repository index refresh | Done | `codira index` reused 232 entries with 0 failures before implementation. |
| Config schema compatibility | Done | Added GPU calibration metadata fields under `embeddings.gpu`; `tests/test_config.py`, `ruff check`, and `ruff format --check` passed for touched Python files. |
| Calibration module and CLI | Done | Added isolated calibration logic, `codira calibrate embeddings`, `--print`, `--write`, and `--output`; `codira calibrate embeddings --print` completed with a TOML snippet in an isolated config environment. |
| Documentation and tests | Done | Added configuration docs and `tests/test_calibration.py`; focused calibration/config/capability tests, `ruff check`, and `ruff format --check` passed. |
| Full validation | Pending | Not started. |

## Constraints

- Calibration output must be valid config TOML.
- Calibration must not mutate user config unless `--write` is used.
- Benchmark execution must be deterministic, offline, bounded, and safe on
  CPU-only systems.
