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

- `codira.arch.no-sqlite3-outside-allowed-layers`
- `codira.arch.no-backend-package-import-outside-allowed-layers`

### Documented future rules

- forbid `codira.storage` imports outside backend implementations and the
  current CLI metadata surface
- forbid `codira.registry` imports outside the current core query/indexing
  entry points

These broader rules are not enforced yet because the current core
implementation still owns transitional responsibilities that would produce
noisy findings.

## Allowlisted Exceptions

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
Context assembly still exposes `sqlite3.Connection` in graph-retrieval request
typing.

Removal condition:
Remove this allowlist entry when context graph queries use a backend-neutral
connection contract.

#### `src/codira/query/graph_enrichment.py`

Rationale:
Graph-enrichment request dataclasses still expose `sqlite3.Connection` for
exact graph lookup reuse.

Removal condition:
Remove this allowlist entry when graph enrichment uses a backend-neutral
connection contract.

#### `src/codira/query/producers.py`

Rationale:
Shared retrieval producer contracts still publish `sqlite3.Connection` in
TYPE_CHECKING-only callable signatures.

Removal condition:
Remove this allowlist entry when producer contracts stop referring to
SQLite-specific connection types.

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

#### `src/codira/sqlite_backend_support.py`

Rationale:
This module is the shared SQLite persistence helper layer used during the
backend packaging migration.

Removal condition:
Remove this allowlist entry when SQLite support helpers move fully behind the
backend package boundary.

### `codira.arch.no-backend-package-import-outside-allowed-layers`

#### `src/codira/indexer.py`

Rationale:
This module still exposes the historical `codira.indexer.SQLiteIndexBackend`
compatibility export through lazy import.

Removal condition:
Remove this allowlist entry when the compatibility export is retired.

#### `packages/codira-backend-duckdb/src/codira_backend_duckdb/__init__.py`

Rationale:
The DuckDB backend currently subclasses the SQLite backend to preserve
behavioral parity with the existing storage contract.

Removal condition:
Remove this allowlist entry when DuckDB no longer inherits from
`SQLiteIndexBackend`.

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
