# codira-backend-duckdb

First-party DuckDB backend plugin for `codira`.

This package adds a file-local DuckDB index backend that integrates with the
standard `codira` backend registry.

Install it with `pip`, not as a system dependency:

```bash
pip install codira-backend-duckdb
```

Repository-local editable install:

```bash
source .venv/bin/activate
pip install -e .
pip install -e packages/codira-backend-duckdb
```

Activate DuckDB for one repository instance:

```bash
export CODIRA_INDEX_BACKEND=duckdb
codira index
```

Verify activation and discovery:

```bash
codira plugins
CODIRA_INDEX_BACKEND=duckdb codira plugins
CODIRA_INDEX_BACKEND=duckdb codira sym helper --json
```

Operator model:

* one backend is active for one repository instance
* DuckDB uses `.codira/index.duckdb` under the repository storage root
* core `codira` remains backend-neutral; this package owns DuckDB bootstrap and
  storage behavior

Good fit:

* local repository indexing
* larger exact-query and embedding inventories than the default SQLite path
* document-heavy or documentation-channel workloads where local analytical
  scans matter more than multi-client shared concurrency

Not the target:

* system-level DuckDB installation
* many active backends for the same repository at once
* remote shared-database deployment semantics

Package-local verification:

```bash
pytest -q packages/codira-backend-duckdb/tests
```
