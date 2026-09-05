# Lint and Semgrep hygiene policy

This policy records the Slice 18 review of every current lint suppression,
Semgrep exception, and repository-owned rule. It is deliberately specific:
new suppressions must either be removed or added here with a concrete owner and
reason. `tests/test_quality_policy.py` prevents a new `# noqa` location from
appearing without this inventory.

## `# noqa` inventory

The review removed two obsolete `E501` suppressions from `tests/test_contracts.py`.
All remaining suppressions name the narrow rule they suppress.

```text
scripts/scriptlib.py:270 PLR0913 — public process runner keeps explicit
    command, environment, and failure-boundary inputs for reusable scripts.
scripts/run_manifest_baseline.py:131 PLR0913 — benchmark invocation inputs are
    independently selectable for reproducible comparisons.
scripts/run_retrieval_quality_benchmark.py:617,913 PLR0913 — result rows and
    benchmark groups preserve explicit provenance and execution inputs.
scripts/run_final_embedding_model_campaign.py:430,575,640,791 PLR0913 — the
    release-campaign artifact functions retain independently auditable inputs.
scripts/run_final_embedding_model_campaign.py:858 C901,PLR0912 — CLI phase
    dispatch is intentionally linear so every restart/checkpoint branch remains visible.
scripts/characterize_similarity_indexes.py:306 PLR0913 — the reproducible
    corpus runner keeps independently selectable corpus and timing inputs.
scripts/generate_github_snapshot.py:118 S607 — the fixed `gh` executable is
    intentionally invoked by argument vector; there is no shell interpolation.
src/codira/indexer.py:1242 PLR0913 — bulk indexing keeps backend, transaction,
    artifact, coverage, and embedding ownership explicit at the orchestration seam.
src/codira/contracts.py:3430 PLR0913 — the plugin protocol signature is a
    public compatibility contract and cannot be bundled without breaking providers.
src/codira/contracts.py:17 EM101,TRY003 — public contract validation keeps
    short, consistent exception messages at the typed boundary.
src/codira/config.py:1403 C901 — configuration semantics remain deliberately
    centralized so versioned breaking-change guidance is deterministic.
src/codira/daemon/service_spec.py:110 PLR0913 — one factory records the full,
    immutable workspace service identity needed by all platform adapters.
src/codira/daemon/launchd.py:159 PLR0913 — injected platform/process seams keep
    launchd rendering deterministic and testable.
src/codira/daemon/runtime.py:123 PLR0913 — foreground daemon dependencies are
    explicit runtime controls rather than hidden globals.
src/codira/migration.py:153 PLR0913 — migration preview reports every resolved
    workspace input without mutating registration state.
src/codira/query_daemon_lifecycle.py:580 PLR0913 — service lifecycle inputs are
    explicit to preserve platform-independent restart behavior.
src/codira/query_daemon_ipc.py:894 PLR0913 — IPC server construction exposes its
    authentication, runtime, and connection-boundary dependencies.
src/codira/cli.py:2139 C901,PLR0912 — index CLI failure/reporting branches are
    deliberately explicit because they are the user-facing command contract.
src/codira/cli.py:5905 PLR0913 — daemon context rendering receives the complete
    explicit query/output/profile request after freshness has been established.
src/codira/cli.py:6732 PLR0913 — command dispatch receives parsed arguments and
    resolved routing/runtime state as one explicit integration boundary.
src/codira/query/context.py:2285 PLR0913 — channel functions share an explicit
    root/query/connection/intent/prefix/profile contract so named similarity
    profiles reach only semantic channels.
src/codira/query/context.py:2427, src/codira/query/context.py:2462,
    src/codira/query/context.py:4018, src/codira/query/context.py:4121, and
    src/codira/query/context.py:4176 retain that same channel-contract reason.
src/codira/docstring.py:1286, src/codira/docstring.py:1397 PLC0415 — lazy imports avoid a configuration or
    registry import cycle on the optional documentation-plugin path.
src/codira/docstring.py:1340, src/codira/docstring.py:1491 PLR0913 — documentation validation preserves
    source, configuration, visibility, and plugin-routing provenance.
src/codira/query_daemon.py:349,366 BLE001 — worker initialization and operation
    failures must cross the future boundary as their original exception.
src/codira/query_daemon_lifecycle.py:721,738 BLE001 — a long-lived service must
    report any unexpected refresh or foreground failure as degraded state.
src/codira/query_daemon_ipc.py:1270,1360 BLE001 — the IPC boundary converts any
    unexpected implementation failure into a stable protocol/unavailable result.
packages/codira-vector-store-sqlite/tests/test_sqlite_vector_store_package.py:454
    BLE001 — the concurrent-writer regression records every thread failure for
    deterministic assertion in the main test thread.
src/codira/mcp/server.py:223 SLF001 — FastMCP exposes no public transport hook;
    its private server object is the required stdio transport boundary.
src/codira/workspace_registry.py:8 TC003 — `Path` is used at runtime in
    descriptor construction as well as annotations.
src/codira/similarity.py:14 EM101,TRY003 — snapshot validation exposes concise,
    stable derived-index errors at the plugin contract boundary.
src/codira/semantic/search.py:20 TC003 — `Path` is a runtime request field at
    the similarity-index boundary.
src/codira/semantic/search.py:193 PLR0913 — candidate discovery keeps explicit
    root, vector-store, profile, and filtering inputs at the query boundary.
tests/test_workspace_registry.py:9 TC003 — `Path` creates runtime fixture paths.
packages/codira-installer/tests/test_tui.py:8 TC003 — `Path` creates runtime TUI
    fixture paths.
packages/codira-analyzer-python/tests/fixtures/runtime_decoupling_baseline.py:3
    F401 — the unused alias is the intentional import artifact under test.
fixtures/packages/codira-backend-duckdb/src/full_index_bulk_violation.py:39 N802
    — the fixture must imitate the production request constructor name to
    trigger the Semgrep rule.

Location aliases for the grouped entries above:
scripts/run_final_embedding_model_campaign.py:575,
scripts/run_final_embedding_model_campaign.py:640,
scripts/run_final_embedding_model_campaign.py:791,
scripts/run_retrieval_quality_benchmark.py:913,
src/codira/docstring.py:1019, src/codira/docstring.py:1114,
src/codira/index_generation.py:115,
src/codira/query_daemon.py:366, src/codira/query_daemon_lifecycle.py:738, and
src/codira/query_daemon_ipc.py:1360 retain the same category-specific reasons
as their immediately preceding grouped entries.
```

## Repository-owned Semgrep rules

Every rule has a violating fixture and is asserted by
`scripts/validate_semgrep_rules.py` and `tests/test_semgrep_rules.py`.

| Rule family | Current purpose |
| --- | --- |
| Analyzer boundaries: `no-storage-import-in-analyzers`, `no-registry-import-in-analyzers`, `no-backend-import-in-analyzers`, `no-sqlite3-in-analyzers`, `require-analyzer-capability-declaration`, `no-host-ast-in-python-analysis` | Keep analyzers storage-, backend-, registry-, and host-parser-independent while requiring a declared capability contract. |
| Core/backend ownership: `no-sqlite3-outside-allowed-layers`, `no-backend-package-import-outside-allowed-layers`, `no-core-schema-ddl-import-in-backends` | Keep physical SQLite/DuckDB schema and package dependencies in their owning layers. |
| DuckDB bulk path: `no-duckdb-executemany-in-support`, `no-duckdb-returning-id-in-support`, `no-store-analysis-in-duckdb-full-index-bulk`, `require-fresh-full-index-embedding-flush`, `no-vector-store-normal-path-in-duckdb-full-index-bulk`, `require-duckdb-full-index-vector-preservation` | Preserve the columnar full-index path, correct ID allocation, and vector reuse semantics. |
| Runtime and plugin boundaries: `no-direct-config-load-in-query-hot-path`, `require-shared-plugin-json-schema-helper`, `no-broad-except-exception`, `no-core-storage-import` | Keep hot paths configuration-free, plugin schemas shared, exceptions narrow, and storage ownership explicit. |
| Determinism: `no-random-without-explicit-seed` | Reject implicit random behavior from reproducible production workflows. |

## Semgrep exceptions and exclusions

There is no repository `.semgrepignore`. Semgrep additionally honors the
repository `.gitignore` for generated/cache paths. All repository-owned rule
exclusions are rule-local; normal full-tree scans also pass `--exclude
fixtures` because the checked-in fixture corpus intentionally violates every
guardrail.
Tests are excluded from production architecture rules because fixtures and
contract tests intentionally import forbidden dependencies to prove a rule
fires; each such rule has a dedicated violating fixture.

- `no-core-storage-import` permits only the SQLite `sqlite_storage.py` and
  DuckDB `repo_storage.py` seams. They centralize the still-required core
  storage path/bootstrap delegation; remove each exclusion when that ownership
  is fully package-local.
- `no-sqlite3-outside-allowed-layers` permits only the three SQLite backend
  modules and the SQLite vector-store module, which own the production SQLite
  schema and connections.
- `no-backend-package-import-outside-allowed-layers` permits only the SQLite
  backend implementation/storage seams, the DuckDB backend/query seams, and
  the demonstration backend. The former import their package-local helpers;
  the latter intentionally teaches extension by composition.
- `no-backend-import-in-analyzers` permits backend schema imports only. Schema
  constants are read-only analyzer metadata, not backend execution coupling.
- Framework-registry `nosemgrep` comments suppress only external rules that
  misclassify Codira DB-API calls as SQLAlchemy/Django sinks. The SQLite and
  DuckDB backend modules own parameterized SQL execution; query-context calls
  use the active backend connection; the two formatted-query suppressions are
  trusted identifier construction inside backend-owned SQL. The DuckDB support
  format-string suppression returns a Python name, not an HTTP response. The
  benchmark dynamic-import suppression loads a locally selected backend-support
  module by trusted argument vector. These exceptions do not affect the
  repository-owned Semgrep rule set.

  Affected sources are
  `scripts/benchmark_index.py`, `src/codira/query/context.py`,
  `packages/codira-backend-sqlite/src/codira_backend_sqlite/__init__.py`,
  `packages/codira-backend-sqlite/src/codira_backend_sqlite/sqlite_support.py`,
  `packages/codira-backend-duckdb/src/codira_backend_duckdb/__init__.py`,
  `packages/codira-backend-duckdb/src/codira_backend_duckdb/duckdb_support.py`,
  and
  `packages/codira-backend-duckdb/src/codira_backend_duckdb/duckdb_query_backend.py`.

## Review outcome

Slice 18 adds `codira.arch.no-host-ast-in-python-analysis`: after the completed
host-target parser migration, a production `ast` import would silently violate
the package-owned Tree-sitter boundary. Its dedicated fixture proves the rule
fires while analyzer tests remain free to compare normalized output with the
host parser.
