<img src="https://raw.githubusercontent.com/marco0560/codira/main/docs/badges/cartoon_cold-2.png" alt="codira badge" width="120">

# codira-analyzer-bash

First-party Bash analyzer plugin for `codira`.

Repository-local editable install:

```bash
source .venv/bin/activate
pip install -e ../codira
pip install -e ../codira/packages/codira-analyzer-bash
```

After installation, verify discovery with:

```bash
codira plugins
codira cov
```

Package-local verification:

```bash
pytest -q packages/codira-analyzer-bash/tests
```
