# Issue 017 Configuration System Execution

## Phase Ledger

- [x] Phase 0 - Baseline verification
- [x] Phase 1 - ADR and public config contract
- [x] Phase 2 - Config schema, paths, loader, merge, validation
- [x] Phase 3 - `codira config` CLI
- [x] Phase 4 - Backend and plugin runtime integration
- [x] Phase 5 - Embedding runtime/model integration
- [x] Phase 6 - First-run generation and repo config tracking
- [x] Phase 7 - Documentation
- [x] Phase 8 - Validation and cleanup

## Evidence Log

| Step | Evidence | Result |
| --- | --- | --- |
| Baseline branch | `git status --short --branch` | Clean `feat/issue-17-configuration-system` branch |
| Capability baseline | `UV_CACHE_DIR=/tmp/uv-cache uv run codira caps --json` | Capability contract available before edits |
| ADR scaffold | `UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/new_decision.py` | Created `docs/adr/ADR-021-codira-configuration-hierarchy-runtime-policy.md` |
| Config tests | `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -q tests/test_config.py` | 8 passed |
| Runtime regression slice | `UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -q tests/test_config.py tests/test_plugins.py tests/test_embeddings.py tests/test_contracts.py -k "config or disable_third_party or active_index_backend or embedding_state or current_embedding"` | 15 passed, 103 deselected |
| Lint slice | `UV_CACHE_DIR=/tmp/uv-cache uv run ruff check ...` | Touched implementation and test files passed |
| Format slice | `UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check ...` | Touched implementation and test files already formatted |
| Codira reindex | `UV_CACHE_DIR=/tmp/uv-cache XDG_CONFIG_HOME=/tmp/codira-index-config uv run codira index` | Indexed 12, reused 215, failed 0 |
| Pre-commit | `UV_CACHE_DIR=/tmp/uv-cache XDG_CONFIG_HOME=/tmp/codira-validation-config uv run pre-commit run --all-files` | Passed |
| Full pytest | `UV_CACHE_DIR=/tmp/uv-cache XDG_CONFIG_HOME=/tmp/codira-validation-config uv run python -m pytest -q` | 368 passed |
| Repository validation | `UV_CACHE_DIR=/tmp/uv-cache XDG_CONFIG_HOME=/tmp/codira-validation-config uv run python scripts/validate_repo.py` | Passed; pytest 368 passed; coverage report written |
