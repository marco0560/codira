# codira-demo-backend

Example third-party backend plugin for `codira`.

This package subclasses the built-in SQLite backend so it can be installed and
discovered through the same plugin contract as an out-of-tree backend.

## Install

```bash
source /path/to/codira/.venv/bin/activate
pip install -e /path/to/codira/examples/plugins/codira_demo_backend
```

## Verify

```bash
codira plugins
CODIRA_INDEX_BACKEND=demo-backend codira index
```
