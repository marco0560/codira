# Issue #27 Plugin Configuration Injection Execution

## Goal

Introduce explicit configuration injection across the core/plugin boundary so
analyzers and backends can be configured through the global Codira
configuration system without hidden global state.

## Ledger

| Step | Status | Evidence |
| --- | --- | --- |
| Baseline branch and worktree check | Done | `git status --short --branch` showed work on `feat/issue-17-configuration-system`. |
| Capability discovery | Done | `codira caps --json` confirmed the issue #17 config surface existed before implementation. |
| Repository index refresh | Done | `codira index` completed with 0 failures before implementation. |
| Phase 1 core contract | Done | Added optional `configure()`, `configuration_json_schema()`, dynamic `[plugins.*]` config tables, registry injection, plugin validation warnings, `enabled` handling, and path-filter-aware scanner/indexer routing. |
| Phase 1 validation | Done | `pytest -q tests/test_config.py tests/test_plugins.py tests/test_contracts.py` passed; ruff passed on touched core files; commit `6152a23`. |
| Phase 2 first-party plugins | Done | Added strict schemas, default-preserving configure hooks, analyzer include/exclude filters, and per-plugin options for Python, JSON, C, C++, Bash, Markdown, Text, SQLite, and DuckDB. |
| Phase 2 validation | Done | Package-local tests for all touched first-party plugins passed; ruff passed on touched package files; commit `282eb42`. |
| Phase 3 docs and versioning | Done | Updated configuration and plugin-model docs, bumped touched plugin distributions and `codira-bundle-official`, refreshed `uv.lock`, and recorded this ledger. |

## Accepted Plugin Options

Common plugin option:

- `enabled: bool = true`

Common analyzer options:

- `include_paths: list[str] = []`
- `exclude_paths: list[str] = []`

First-party plugin-specific options:

- `analyzer-python`: `emit_module_documentation`, `emit_imports`,
  `emit_constants`, `emit_type_aliases`
- `analyzer-json`: `enabled_families`, `emit_dependencies`, `emit_scripts`,
  `emit_schema_properties`
- `analyzer-c`: `use_leading_comments`, `emit_doxygen_documentation`,
  `include_system_includes`, `emit_macros`
- `analyzer-cpp`: `use_leading_comments`, `emit_doxygen_documentation`,
  `include_system_includes`, `emit_namespaces`, `emit_macros`
- `analyzer-bash`: `emit_functions`
- `analyzer-markdown`: `strip_front_matter`,
  `emit_file_artifact_without_headings`, `min_heading_level`,
  `max_heading_level`
- `analyzer-text`: `include_root_files`, `include_docs_directories`,
  `exclude_generated`, `exclude_fixtures_logs`
- `backend-sqlite`: common plugin options only
- `backend-duckdb`: common plugin options only

## Constraints

- Configuration injection remains optional for third-party plugins.
- Plugins do not access global config directly.
- First-party plugin schemas are strict.
- Analyzer configuration changes affect persisted analyzer inventory through a
  deterministic configuration fingerprint.
