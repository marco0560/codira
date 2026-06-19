# Test Current Situation

Date: 2026-06-18

## Scope

This report compares the documented architecture and ADR surface with the
current automated test surface. It focuses on documented contracts, runtime
configuration, and functions whose behavior is not strongly protected by tests.

Inputs reviewed:

- `docs/architecture/*.md`
- `docs/adr/*.md`
- `docs/configuration.md`
- `docs/plugins/*.md`
- `tests/**/*.py`
- `packages/*/tests/**/*.py`
- selected implementation entry points referenced by the architecture documents

Method:

- Indexed the repository with `codira`.
- Reviewed the capability surface through `codira caps --json`.
- Read the architecture and ADR documents.
- Compared documented contracts against tests and package-local tests.
- Used direct symbol/test references as a weak signal, then checked important
  surfaces manually against behavior-oriented tests.

Coverage labels:

- Strong: a test directly asserts the documented behavior or invariant.
- Partial: behavior is exercised indirectly, or only the happy path is covered.
- Weak: a function or documented item has little or no observed behavioral test
  protection.
- Not testable as written: the item is roadmap, policy, or external process and
  should be protected by validation scripts or release checks instead of unit
  tests.

## Executive Summary

Codira has strong tests around the core indexing contract, backend selection,
incremental freshness, retrieval merge behavior, plugin package entry points,
configuration parsing, calibration output, and analyzer package metadata.

The largest unprotected or weakly protected areas are:

1. CLI command wrappers and output renderers.
2. Runtime configuration propagation into commands that do not explicitly carry a
   repository root.
3. CI/platform policy encoded in workflow files.
4. Private orchestration helpers in the indexer, registry, scanner, and query
   graph expansion layers.
5. Release/distribution ADRs whose process guarantees are documented but not
   enforced by tests.
6. Benchmark and maintenance scripts that encode important operational behavior
   but have little direct test coverage.

The most important near-term test additions are not broad coverage expansion.
They are focused regression tests for repo-local configuration propagation and
CI/runtime policy drift.

## Strongly Protected Areas

### Backend And Storage Contracts

Status: Strong

Protected by:

- `tests/test_contracts.py`
- `tests/test_memory_backend.py`
- `tests/test_plugins.py`
- `tests/test_incremental_indexing.py`
- `packages/codira-backend-sqlite/tests/`
- `packages/codira-backend-duckdb/tests/`

Covered behavior includes:

- backend protocol shape and required operations
- memory backend parity with SQLite for contract validation
- default SQLite backend selection
- DuckDB backend entry point discovery
- repo-configured backend selection
- backend isolation across roots
- index freshness metadata
- incremental reuse/rebuild behavior
- deletion, stale row cleanup, and coverage issue persistence

Remaining gap:

- backend-specific performance characteristics are protected by benchmark
  artifacts, not by ordinary tests. That is appropriate, but it means
  performance regressions can still pass the test suite.

### Analyzer Package Contracts

Status: Strong

Protected by:

- package-local analyzer tests under `packages/codira-analyzer-*/tests/`
- `tests/test_plugins.py`
- `tests/test_incremental_indexing.py`
- `tests/test_capabilities.py`

Covered behavior includes:

- analyzer plugin registration
- first-party analyzer package metadata
- analyzer option schemas
- analyzer ordering
- Python, C, C++, Bash, JSON, Markdown, and text analyzer behavior
- strict coverage auditing for analyzer/glob mismatches
- plugin configuration fingerprint behavior for analyzer rebuilds

Remaining gap:

- some private parser helpers are only protected through emitted analyzer output,
  not through focused unit tests.

### Configuration Schema And Rendering

Status: Strong for schema parsing and rendering, partial for runtime
propagation.

Protected by:

- `tests/test_config.py`
- `tests/test_calibration.py`
- `tests/test_embeddings.py`
- `tests/test_incremental_indexing.py`

Covered behavior includes:

- `load_effective_config`
- `validate_config_mapping`
- `profile_config`
- `full_profile_config`
- `render_config_toml`
- `write_config_file`
- `config_to_mapping`
- configuration profile rendering
- disabled analyzers
- invalid GPU memory minimums
- calibration output and TOML writes
- embedding batch/thread environment overrides
- repo-configured backend selection during indexing

Remaining gaps:

- not every command-level runtime path proves that repo-local `.codira/config.toml`
  is passed into lower-level helpers
- workflow and Python runtime policy are not asserted by tests
- some config file mutation helpers have limited direct coverage

### Query, Retrieval, And Context Assembly

Status: Strong for public behavior, partial for graph helper internals.

Protected by:

- `tests/test_retrieval_merge.py`
- `tests/test_context_rendering.py`
- `tests/test_characterization_phase2.py`
- `tests/test_call_graph.py`
- `tests/test_semantic_backend_search.py`
- `tests/test_capabilities.py`

Covered behavior includes:

- retrieval candidate merge and de-duplication
- exact winner dominance
- role and capability signals
- output caps
- producer descriptors
- planner channel selection for architecture/config/test queries
- context rendering with provenance
- call graph and reference query behavior

Remaining gap:

- internal graph expansion helpers are not strongly protected as separate units.
  Most coverage is through CLI or context behavior.

### Semgrep And Process Guardrails

Status: Strong for rule inventory and fixtures.

Protected by:

- `tests/test_semgrep_rules.py`
- `scripts/validate_semgrep_rules.py`
- `scripts/validate_repo.py`

Covered behavior includes:

- rule metadata inventory
- fixture validation
- repository validation script integration

Remaining gap:

- validation script behavior is tested mostly at the inventory level. Subprocess
  failure modes and missing external tool behavior are only partially covered.

## ADR Coverage Matrix

| ADR | Topic | Coverage Status | Notes |
| --- | --- | --- | --- |
| ADR-001 | Hybrid exact and semantic search | Partial | Current retrieval behavior is tested, but the original RRF-specific contract is not strongly asserted as a formula-level invariant. |
| ADR-002 | Prefix-based indexing and querying | Strong | Prefix filtering and CLI/query behavior are covered by `tests/test_prefix_filtering.py` and indexing tests. |
| ADR-003 | JSON output contract | Strong | JSON command output has focused CLI tests. |
| ADR-004 | Plugin architecture | Strong | Entry point discovery, analyzer order, default backend, DuckDB backend, and plugin command behavior are covered. Private registry internals remain partial. |
| ADR-005 | Embedding cache and durable identity | Strong | Incremental indexing and embedding reuse/recompute behavior are covered. Performance remains benchmark-only. |
| ADR-006 | Capability signal taxonomy | Strong | Capability contract and retrieval signal behavior are covered. |
| ADR-007 | First-party plugin packaging | Partial | Package metadata and plugin registration are covered. Full release/install behavior is process-level, not test-level. |
| ADR-008 | Batched embeddings and runtime tuning | Partial | Batch/thread/env/config behavior is covered. Real model throughput and GPU behavior are benchmark/manual surfaces. |
| ADR-009 | End-user distribution | Partial | Metadata and install helpers have some coverage. Real PyPI/TestPyPI publishing is not test-protected. |
| ADR-010 | Call graph queries | Strong | Call/ref query behavior and graph rendering are covered at public surface level. |
| ADR-011 | Generated repository template | Weak | Template/process behavior is not broadly protected in this repository test suite. |
| ADR-012 | Multi-repository development | Weak | Operational policy is documented but not fully enforced by tests. |
| ADR-013 | Project-local generated repositories | Weak | Mostly process-level. No strong regression tests found for the generated repository lifecycle. |
| ADR-014 | Release coordination | Partial | Version metadata and validation scripts help, but release choreography is not end-to-end tested. |
| ADR-015 | Roadmap and project planning | Not testable as written | Should remain protected by roadmap snapshots and process checks, not unit tests. |
| ADR-016 | Symbol overload support | Strong | Overload metadata and retrieval behavior are covered. |
| ADR-017 | Python runtime support | Partial | Package `requires-python` metadata is visible in tests, but workflow Python version drift is not directly asserted. |
| ADR-018 | CI platform coverage | Weak | CI workflow contents are not strongly tested against the documented platform policy. |
| ADR-019 | Analyzer/backend freshness | Strong | Runtime and analyzer inventory rebuild behavior is covered. |
| ADR-020 | Backend isolation and smoke tests | Strong | Backend environment isolation and smoke behavior are covered. |
| ADR-021 | Configuration hierarchy and runtime policy | Partial | Schema/default/rendering behavior is strong. Runtime propagation into every command path is not fully protected. |

## Configuration Items With Weak Or Partial Protection

### CI And Runtime Policy

Status: Weak

Items:

- `.github/workflows/ci.yml` Python version
- `.github/workflows/docs.yml` Python version
- `.python-version`
- `pyproject.toml` `requires-python`
- package-local `requires-python` declarations

Observed protection:

- package metadata is checked in package tests.
- no strong test was found that asserts GitHub workflow files continue to use
  Python 3.13.

Risk:

- a future workflow edit can silently move CI to Python 3.14 or another runtime
  even if package metadata still says `>=3.13`.

Recommended test:

- add a small workflow policy test that parses `.github/workflows/*.yml` and
  asserts the approved Python version and required validation commands.

### Repository-Local Configuration Propagation

Status: Partial

Items:

- `[backend] name`
- `[embeddings] enabled`
- `[embeddings.indexing] mode`
- `[embeddings.indexing] object_types`
- `[analyzers.<name>] enabled`
- `[plugins.<package>] enabled`
- command paths that call `load_effective_config`

Observed protection:

- repo-configured backend selection during indexing is covered.
- disabled analyzer and plugin configuration are covered.
- embedding disable behavior is covered through isolated user-level config.
- configuration parsing, rendering, validation, and calibration writes are
  covered.

Remaining risk:

- commands that do not carry an explicit repository root can still drift toward
  user/default configuration instead of repo configuration.
- this is especially important for command wrappers, capability reporting, and
  semantic runtime helpers.

Recommended tests:

- run `codira caps --json` from a temporary repository with repo-local analyzer
  configuration and assert the capability contract reflects the repo config.
- run semantic search/indexing from a temporary repository with repo-local
  embedding configuration and assert the lower-level runtime helper observes the
  repo config.
- add a regression test for command execution from outside the target root when
  a path argument points at a repository with `.codira/config.toml`.

### Config File Mutation Commands

Status: Partial

Functions:

- `src/codira/config.py::ensure_user_config`
- `src/codira/config.py::update_config_file`
- `src/codira/config.py::load_config_level`
- `src/codira/config.py::explain_key`
- `src/codira/config.py::repo_config_path`

Observed protection:

- config init and rendering are tested.
- load/merge behavior is tested.

Remaining risk:

- level-specific read/write behavior, explanation output, and existing-file
  mutation paths do not have the same level of regression protection as schema
  validation.

Recommended tests:

- assert `config explain` reports the correct source level for repo, user,
  system, environment, and default values.
- assert `config set` or equivalent mutation preserves unrelated keys.
- assert auto user config creation does not happen for commands documented as
  non-mutating when that behavior matters.

### Embedding Runtime Tuning

Status: Partial

Items:

- `embeddings.model`
- `embeddings.version`
- `embeddings.dimension`
- `embeddings.batch_size`
- `embeddings.device`
- `embeddings.gpu.device_id`
- `embeddings.gpu.memory_limit_mb`
- `CODIRA_EMBED_BATCH_SIZE`
- `CODIRA_TORCH_NUM_THREADS`
- `CODIRA_TORCH_NUM_INTEROP_THREADS`

Observed protection:

- config parsing/rendering is tested.
- environment override behavior for batch size and torch threads is tested.
- calibration output is tested.

Remaining risk:

- real hardware selection and GPU memory enforcement are not test-protected.
- model identity, dimension, and version invalidation are mostly protected
  through indexing behavior, not a focused semantic runtime contract.

Recommended tests:

- keep real GPU behavior out of unit tests.
- add mocked runtime tests for hardware detection and model/device selection.
- add focused tests for model/version/dimension changes causing expected
  embedding invalidation behavior.

### Plugin Configuration Defaults

Status: Partial

Items:

- first-party plugin default config schemas
- `FIRST_PARTY_PLUGIN_DEFAULT_CONFIGS`
- `PLUGIN_OPTION_SCHEMAS`
- plugin-specific analyzer options such as `tree_sitter`, `emit_macros`,
  `include`, and `exclude`

Observed protection:

- package-local analyzer tests cover many plugin options.
- config schema rendering includes first-party plugin defaults.
- analyzer inventory fingerprints include plugin config.

Remaining risk:

- generic plugin enablement and option schema validation are better covered than
  every plugin option's behavioral effect.

Recommended tests:

- for each first-party analyzer option exposed in config, keep one package-local
  test proving that changing the option changes analysis behavior or analyzer
  metadata as intended.

## Function Surfaces With Weak Or Indirect Protection

This section lists functions and groups where no direct or only indirect
behavioral protection was observed. It is intentionally risk-oriented; it does
not claim every helper is untested in a semantic sense.

### `src/codira/cli.py`

Status: Partial

Weakly protected function groups:

- command wrapper functions such as `_run_capabilities`, `_run_coverage`,
  `_run_embeddings`, `_run_documentation_lookup`
- config command wrappers such as `_run_config_init`, `_run_config_show`,
  `_run_config_set`, `_run_config_explain`
- relation and graph output helpers such as `_render_relation_tree`,
  `_render_dot_graph`, `_render_grouped_call_tree`, `_render_grouped_ref_tree`
- markdown/table rendering helpers such as `_format_capability_table`,
  `_render_capabilities_markdown`, `_print_coverage_report`

Why it matters:

- CLI wrappers are the layer where repository root, output format, command
  defaults, and error handling meet. A helper can be internally correct while
  the command passes the wrong root or renders stale policy.

Recommended tests:

- add CLI-level tests for each documented command family in JSON mode.
- add one text-mode smoke test per renderer where text output is documented.
- prefer temporary repositories with repo-local config to catch root propagation
  drift.

### `src/codira/config.py`

Status: Strong for schema; partial for helpers.

Weakly protected functions:

- `repo_config_path`
- `_leaf_keys`
- `_validate_known_keys`
- `_validate_schema_types`
- `_validate_int_minimums`
- `_validate_plugin_semantics`
- `_validate_embedding_indexing_semantics`
- `_environment_overrides`
- `update_config_file`
- `ensure_user_config`
- `load_config_level`
- `explain_key`

Why it matters:

- the config hierarchy is an ADR-level contract. Helper drift can affect command
  behavior even if default rendering remains correct.

Recommended tests:

- table-driven tests for source precedence and source explanation.
- mutation tests that preserve comments/unrelated keys if that is a supported
  behavior.
- negative tests for unknown keys and invalid plugin semantics.

### `src/codira/semantic/embeddings.py`

Status: Partial

Weakly protected functions:

- `get_embedding_backend`
- `embeddings_enabled`
- `_configured_embedding_batch_size`
- `_configured_embedding_device`
- `_configure_torch_runtime`
- `_model_for_device`
- `_resolve_embedding_device`
- `_torch_threads_from_env`

Why it matters:

- this module is the runtime bridge between persistent config, environment
  overrides, torch runtime setup, and embedding backend behavior.

Observed protection:

- batch size and thread environment overrides are tested.
- embedding disable behavior is tested through isolated user-level config.

Remaining risk:

- repo-root-specific runtime behavior is not comprehensively proven for every
  command path.

Recommended tests:

- test repo-local embedding config through public CLI/index/search paths.
- test mocked torch runtime setup for CPU/CUDA/MPS without requiring hardware.

### `src/codira/calibration.py`

Status: Partial

Weakly protected functions:

- `detect_hardware`
- `deterministic_embedding_samples`
- `safe_fallback_candidate`
- `_is_oom_error`
- `_configure_torch_threads`
- `_model_for_device`

Observed protection:

- calibration output, TOML rendering, GPU memory limits, and torch thread
  rendering are covered.

Remaining risk:

- hardware detection and out-of-memory fallback behavior are mostly unprotected
  unless mocked by focused tests.

Recommended tests:

- add pure mocked tests for hardware profile detection.
- add OOM classification tests around the exact expected exception strings.

### `src/codira/indexer.py`

Status: Strong for end-to-end behavior; partial for private orchestration.

Weakly protected function groups:

- `_audit_canonical_directory_coverage`
- `_embedding_indexing_policy`
- `_collect_project_scan_state`
- `_load_existing_index_state`
- `_plan_index_run`
- `_prepare_index_storage`
- `_index_run_mutated_graph_inputs`
- `_finalize_index_report`

Observed protection:

- `index_repo` behavior has broad scenario coverage.
- incremental reuse, embedding modes, object types, coverage, deletion, and
  config-triggered rebuilds are covered.

Remaining risk:

- private plan/finalization helpers can regress in edge cases not represented by
  current end-to-end scenarios.

Recommended tests:

- keep most tests at `index_repo` level.
- add focused tests only for edge cases where a private helper has previously
  caused a regression.

### `src/codira/registry.py`

Status: Strong for public plugin behavior; partial for discovery internals.

Weakly protected functions:

- `_discover_entry_point_plugins`
- `_load_entry_point_plugin`
- `_resolve_plugins`
- `_apply_enabled_plugin_config`
- `_plugin_cache_key`
- `_invalidate_plugin_cache`

Observed protection:

- public plugin behavior and root-aware backend selection are covered.

Remaining risk:

- cache-key composition and root-aware config invalidation can regress without
  direct tests on mixed-root scenarios.

Recommended tests:

- keep temporary-root tests for backend and analyzer config.
- add one mixed-root cache test for analyzer enablement, not only backend
  selection.

### `src/codira/scanner.py` And `src/codira/repository_scope.py`

Status: Partial

Weakly protected functions:

- `_load_gitignore`
- `_match_gitignore`
- `_is_excluded`
- `_project_roots`
- repository scope helper functions in `repository_scope.py`

Observed protection:

- public file iteration and metadata behavior are covered.

Remaining risk:

- gitignore edge cases, nested roots, symlink behavior, and generated artifact
  exclusions can drift.

Recommended tests:

- table-driven scanner tests for nested `.gitignore`, generated directories,
  symlinks, hidden files, and explicit prefix boundaries.

### `src/codira/query/exact.py`

Status: Partial

Weakly protected functions:

- `build_call_tree`
- `build_ref_tree`
- internal tree assembly helpers

Observed protection:

- call/ref query behavior is covered through public surfaces.

Remaining risk:

- tree depth, duplicate elimination, and display shape can regress if only the
  flat query path is asserted.

Recommended tests:

- add focused CLI JSON tests for call/ref tree output with depth, reverse edges,
  and repeated symbols.

### `src/codira/query/graph_enrichment.py`

Status: Partial

Weakly protected functions:

- `expand_graph_related_symbols`
- call/reference/include expansion helpers
- overload and relationship filtering helpers

Observed protection:

- context assembly and retrieval characterization tests exercise the feature
  indirectly.

Remaining risk:

- graph expansion policy can drift without a clear failing unit test.

Recommended tests:

- add small in-memory graph fixtures that assert exact expansion results for
  includes, calls, refs, overloads, and depth cutoffs.

### `src/codira/query/producers.py`

Status: Partial

Weakly protected functions:

- `channel_producer_specs`
- producer selection and descriptor helpers not directly asserted by name

Observed protection:

- retrieval merge and capability metadata are tested.

Remaining risk:

- producer descriptor drift can affect `ctx --explain` and capability output
  without breaking retrieval behavior.

Recommended tests:

- assert producer descriptors are stable for architecture, config, tests,
  symbol, and semantic query intents.

### `src/codira/parser_ast.py` And `src/codira/normalization.py`

Status: Partial

Weakly protected function groups:

- Python AST predicate helpers
- import extraction helpers
- stable symbol ID helpers
- normalization helpers for display/signature/source path fields

Observed protection:

- analyzer and parser-facing behavior is covered through emitted symbol tests.

Remaining risk:

- many helper edge cases are only covered if a language analyzer test happens to
  emit that construct.

Recommended tests:

- add focused fixtures for decorators, overloads, nested classes, relative
  imports, re-exports, generated paths, and duplicate local names.

### `src/codira/storage.py`

Status: Partial

Weakly protected functions:

- storage path helpers
- lock path helpers
- backend override helpers outside the common path

Observed protection:

- active backend override and lock-related behavior are partially covered.

Remaining risk:

- path-level behavior can drift on non-default output directories.

Recommended tests:

- add tests for explicit output directory, alternate repository root, and lock
  file path selection.

### Scripts

Status: Partial to weak

Weakly protected script areas:

- benchmark campaign orchestration
- benchmark timing metadata parsing
- release and validation helper edge cases
- GitHub snapshot pagination/failure behavior
- decision/ADR generation helpers
- repository cleaning and artifact maintenance helpers

Observed protection:

- bootstrap and validation script tests cover important inventories and process
  files.

Remaining risk:

- operational scripts can drift while the library test suite remains green.

Recommended tests:

- add dry-run or fixture-based tests for scripts that write files, call GitHub,
  or orchestrate benchmark runs.

## Documentation Items That Are Not Fully Test-Protected

### Architecture Documents

Strongly protected architecture:

- backend abstraction and indexing lifecycle
- plugin discovery and analyzer activation
- query pipeline public behavior
- configuration schema/default rendering

Partially protected architecture:

- CLI renderer behavior
- planner and producer explanation text
- storage backend performance expectations
- scanner/generated-file exclusion policy
- release and package boundary process

Weakly protected architecture:

- generated repository workflow
- multi-repository release coordination
- external publishing process
- CI platform policy

### Configuration Documentation

Strongly protected:

- default config shape
- full config profile rendering
- validation of several invalid values
- calibration-generated config output

Partially protected:

- exact source explanation for every config key
- level-specific writes and reads
- repo-local config propagation through all command families
- runtime behavior of every first-party plugin option

Weakly protected:

- examples in documentation are not systematically executed.
- workflow and platform examples are not parsed by tests.

## Recommended Test Plan

### Priority 1: Configuration And Runtime Drift

Add tests for:

1. `.github/workflows/*.yml` Python version and required validation commands.
2. `.python-version` consistency with workflow and package metadata.
3. `codira caps --json` from a repo with repo-local analyzer config.
4. semantic embedding runtime behavior from a repo with repo-local embedding
   config.
5. command execution from outside the target repo while passing a path to a repo
   containing `.codira/config.toml`.

Reason:

- these are high-impact surfaces where recent work has already shown that root
  propagation matters.

### Priority 2: CLI Output Contracts

Add tests for:

1. `caps --json` and markdown/text output.
2. `config explain` for each config source level.
3. `calls` and `refs` tree/DOT output with depth and duplicate edges.
4. `cov` and `docs` command output with documented flags.

Reason:

- CLI wrappers are thin but high-risk because they bind config, root, output, and
  backend behavior.

### Priority 3: Focused Helper Tests For Regression-Prone Internals

Add tests for:

1. registry mixed-root plugin cache behavior
2. scanner `.gitignore` and generated directory edge cases
3. graph enrichment depth and relation filtering
4. parser/normalization fixtures for overloads, decorators, re-exports, and
   duplicate local names
5. mocked calibration hardware and OOM fallback behavior

Reason:

- these helpers encode edge cases that are expensive to diagnose from only
  end-to-end failures.

### Priority 4: Process And Script Guardrails

Add tests or validation checks for:

1. release coordination metadata
2. generated repository template assumptions
3. benchmark script dry-run behavior
4. GitHub snapshot pagination and schema failures

Reason:

- these are not always library unit-test surfaces, but they protect documented
  operational guarantees.

## Non-Goals

The following should not be forced into ordinary unit tests:

- real GPU performance
- real PyPI/TestPyPI publishing
- full benchmark matrix execution
- GitHub network behavior
- long-running embedding matrix runs

These should remain protected by mocked tests, dry-run validation, benchmark
artifacts, and documented process gates.

## Bottom Line

The test suite protects the main product behavior well. The current risk is not
that core indexing or backend behavior is untested; it is that command-level
configuration propagation, CI/runtime policy, and process-heavy ADRs can drift
without failing tests.

The next useful coverage work should be narrow:

1. workflow/runtime policy tests
2. repo-local config propagation tests across command families
3. CLI output contract tests for documented modes
4. small helper tests for registry, scanner, graph enrichment, and semantic
   runtime edge cases
