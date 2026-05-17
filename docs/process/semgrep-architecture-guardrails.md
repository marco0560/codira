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
- `codira.plugins.no-broad-except-exception`

### Enforced with allowlist

- `codira.plugins.no-core-storage-import`
- `codira.arch.no-sqlite3-outside-allowed-layers`
- `codira.arch.no-backend-package-import-outside-allowed-layers`

### Documented future rules

- forbid `codira.registry` imports outside the current core query/indexing
  entry points

This broader rule is not enforced yet because the current core implementation
still owns transitional responsibilities that would produce noisy findings.

## Allowlisted Exceptions

### `codira.plugins.no-core-storage-import`

#### `packages/codira-backend-sqlite/src/codira_backend_sqlite/sqlite_storage.py`

Rationale:
This package-local seam centralizes SQLite bootstrap/path imports so the
production backend no longer imports `codira.storage` directly.

Removal condition:
Remove this allowlist entry when SQLite bootstrap/path ownership no longer
delegates to core storage helpers.

#### `packages/codira-backend-duckdb/src/codira_backend_duckdb/sqlite_storage_compat.py`

Rationale:
This package-local seam centralizes the localized DuckDB compatibility layer's
remaining SQLite bootstrap/path imports.

Removal condition:
Remove this allowlist entry when DuckDB no longer needs compatibility access
to the SQLite bootstrap/path surface.

#### `packages/codira-backend-duckdb/src/codira_backend_duckdb/repo_storage.py`

Rationale:
This package-local seam centralizes the production DuckDB backend's remaining
generic repository-storage imports for `.codira` directory and metadata
ownership.

Removal condition:
Remove this allowlist entry when those storage-path/metadata helpers no longer
delegate to core storage helpers.

### `codira.arch.no-sqlite3-outside-allowed-layers`

#### `src/codira/storage.py`

Rationale:
This module still owns the repository-local SQLite storage implementation and
schema application helpers.

Removal condition:
Remove this allowlist entry when SQLite-specific persistence logic no longer
lives in core storage helpers.

#### `src/codira/cli.py`

Rationale:
The CLI still performs SQLite-shaped freshness and rebuild inspection during
index lifecycle checks.

Removal condition:
Remove this allowlist entry when CLI rebuild inspection delegates fully to the
active backend contract.

#### `src/codira/query/context.py`

Rationale:
Context assembly still catches `sqlite3.OperationalError` around the legacy
optional `docstrings` table lookup path.

Removal condition:
Remove this allowlist entry when optional docstring lookup no longer depends on
SQLite driver exceptions in core query assembly.

#### `packages/codira-backend-sqlite/src/codira_backend_sqlite/__init__.py`

Rationale:
This is the production SQLite backend implementation.

Removal condition:
No removal planned while SQLite remains a supported backend.

#### `packages/codira-backend-duckdb/src/codira_backend_duckdb/__init__.py`

Rationale:
The DuckDB backend still reuses SQLite-shaped compatibility helpers and error
handling during the current parity phase.

Removal condition:
Remove this allowlist entry when DuckDB no longer depends on SQLite driver
types or compatibility helpers.

#### `packages/codira-backend-sqlite/src/codira_backend_sqlite/sqlite_support.py`

Rationale:
This module is now the package-owned SQLite persistence helper layer and
imports `sqlite3` as part of the supported production backend.

Removal condition:
No removal planned while SQLite remains a supported backend.

### `codira.arch.no-backend-package-import-outside-allowed-layers`

#### `src/codira/indexer.py`

Rationale:
This module still exposes the historical `codira.indexer.SQLiteIndexBackend`
compatibility export through lazy import.

Removal condition:
Remove this allowlist entry when the compatibility export is retired.

#### `packages/codira-backend-sqlite/src/codira_backend_sqlite/__init__.py`

Rationale:
The SQLite backend package now imports its helper implementation from the
package-local `sqlite_support` module.

Removal condition:
Remove this allowlist entry when the backend module no longer needs a separate
package-local helper module.

#### `packages/codira-backend-duckdb/src/codira_backend_duckdb/__init__.py`

Rationale:
The DuckDB backend still owns package-local bootstrapping, compatibility
wrappers, and package-local helper imports while the standalone migration is
in progress.

Removal condition:
Remove this allowlist entry when the production backend no longer needs local
helper-module imports that match the backend-package guardrail.

#### `packages/codira-backend-duckdb/src/codira_backend_duckdb/sqlite_compatible_backend.py`

Rationale:
This temporary DuckDB-local compatibility module preserves SQLite-shaped query
and maintenance semantics without importing the SQLite backend package at
runtime.

Removal condition:
Remove this allowlist entry when DuckDB no longer needs the localized
SQLite-compatible surface.

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
