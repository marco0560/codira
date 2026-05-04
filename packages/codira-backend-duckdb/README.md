# codira-backend-duckdb

First-party DuckDB backend plugin scaffold for `codira`.

Repository-local editable install:

```bash
source .venv/bin/activate
pip install -e ../codira
pip install -e ../codira/packages/codira-backend-duckdb
```

After installation, verify discovery with:

```bash
codira plugins
CODIRA_INDEX_BACKEND=duckdb codira plugins
```

Package-local verification:

```bash
pytest -q packages/codira-backend-duckdb/tests
```

Notes:

* this package is intentionally scaffold-only in Phase 2
* lifecycle, query, and persistence behavior are implemented in later phases
