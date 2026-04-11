# codira-backend-sqlite

First-party SQLite backend plugin for `codira`.

Repository-local editable install:

```bash
source .venv/bin/activate
pip install -e ../codira
pip install -e ../codira/packages/codira-backend-sqlite
```

After installation, verify discovery with:

```bash
codira plugins
codira emb "symbol lookup" --json
```

Package-local verification:

```bash
pytest -q packages/codira-backend-sqlite/tests
```
