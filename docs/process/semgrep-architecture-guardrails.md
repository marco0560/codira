# Semgrep Architecture Guardrails

## Purpose

This note records the Codira-owned Semgrep guardrails introduced for issue
`#13`.

It exists to:

- classify which rules are enforced now
- record the current allowlisted architectural debt explicitly
- define the removal condition for each temporary exception

## Rule Status Matrix

### Enforced now

- `codira.arch.no-storage-import-in-analyzers`
- `codira.arch.no-registry-import-in-analyzers`
- `codira.arch.no-backend-import-in-analyzers`
- `codira.arch.no-sqlite3-in-analyzers`
- `codira.arch.require-analyzer-capability-declaration`
- `codira.arch.no-duckdb-executemany-in-support`
- `codira.arch.no-duckdb-returning-id-in-support`
- `codira.arch.no-store-analysis-in-duckdb-full-index-bulk`
- `codira.arch.no-direct-config-load-in-query-hot-path`
- `codira.plugins.no-broad-except-exception`

### Enforced with allowlist

- `codira.plugins.no-core-storage-import`
- `codira.arch.no-sqlite3-outside-allowed-layers`
- `codira.arch.no-backend-package-import-outside-allowed-layers`

### Documented future rules

- forbid `codira.registry` imports outside the current core query/indexing
  entry points
- forbid direct backend/vector-store/embedding-engine resolution in query hot
  paths once those paths are fully migrated to the command-scoped runtime
  context

This broader rule is not enforced yet because the current core implementation
still owns transitional responsibilities that would produce noisy findings.

### `codira.arch.no-direct-config-load-in-query-hot-path`

Rationale:
Benchmark campaign `20260627T201446` showed repeated effective-config loading
and TOML parsing as a measurable `ctx` overhead. Query hot paths should receive
configuration through command-scoped runtime state instead of parsing config
files directly.

Removal condition:
No removal planned while query commands remain performance-sensitive.

### `codira.arch.no-store-analysis-in-duckdb-full-index-bulk`

Rationale:
DuckDB full-index persistence must stay on the backend-native bulk path. Calling
the legacy per-file `_store_analysis` helper from `persist_full_index` would
reintroduce the row-oriented write shape that benchmark profiling identified as
the DuckDB full-index bottleneck.

Removal condition:
No removal planned while DuckDB remains a supported full-index backend.

## Allowlisted Exceptions

### `codira.plugins.no-core-storage-import`

#### `packages/codira-backend-sqlite/src/codira_backend_sqlite/sqlite_storage.py`

Rationale:
This package-local seam centralizes SQLite bootstrap/path imports so the
production backend no longer imports `codira.storage` directly.

Removal condition:
Remove this allowlist entry when SQLite bootstrap/path ownership no longer
delegates to core storage helpers.

#### `packages/codira-backend-duckdb/src/codira_backend_duckdb/repo_storage.py`

Rationale:
This package-local seam centralizes the production DuckDB backend's remaining
generic repository-storage imports for `.codira` directory and metadata
ownership.

Removal condition:
Remove this allowlist entry when those storage-path/metadata helpers no longer
delegate to core storage helpers.

### `codira.arch.no-sqlite3-outside-allowed-layers`

#### `packages/codira-backend-sqlite/src/codira_backend_sqlite/__init__.py`

Rationale:
This is the production SQLite backend implementation.

Removal condition:
No removal planned while SQLite remains a supported backend.

#### `packages/codira-backend-sqlite/src/codira_backend_sqlite/sqlite_storage.py`

Rationale:
This module owns SQLite database path resolution, schema bootstrap, and schema
refresh behavior for the production SQLite backend.

Removal condition:
No removal planned while SQLite remains a supported backend.

#### `packages/codira-backend-sqlite/src/codira_backend_sqlite/sqlite_support.py`

Rationale:
This module is now the package-owned SQLite persistence helper layer and
imports `sqlite3` as part of the supported production backend.

Removal condition:
No removal planned while SQLite remains a supported backend.

#### `packages/codira-vector-store-sqlite/src/codira_vector_store_sqlite/__init__.py`

Rationale:
This is the production SQLite vector-store implementation and owns the
separated `.codira/embeddings.db` schema.

Removal condition:
No removal planned while SQLite remains a supported vector store.

### `codira.arch.no-backend-package-import-outside-allowed-layers`

#### `packages/codira-backend-sqlite/src/codira_backend_sqlite/__init__.py`

Rationale:
The SQLite backend package now imports its helper implementation from the
package-local `sqlite_storage` and `sqlite_support` modules.

Removal condition:
Remove this allowlist entry when the backend module no longer needs a separate
package-local helper module.

#### `examples/plugins/codira_demo_backend/src/codira_demo_backend/__init__.py`

Rationale:
The example backend intentionally demonstrates extension by reusing the SQLite
backend implementation.

Removal condition:
Remove this allowlist entry when the example backend becomes standalone or is
replaced.

## Local Commands

Repository validation:

```bash
uv run python scripts/validate_repo.py
```

Direct Semgrep scan:

```bash
uv run python scripts/run_repo_tool.py semgrep scan --config semgrep/rules --metrics=off --disable-version-check .
```
