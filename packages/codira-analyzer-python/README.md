<img src="https://raw.githubusercontent.com/marco0560/codira/main/docs/badges/cartoon_cold-2.png" alt="codira badge" width="120">

# codira-analyzer-python

First-party Python analyzer plugin for `codira`.

## Syntax contract

`codira_analyzer_python.syntax` owns a normalized Tree-sitter Python syntax
tree. It reports provider-neutral node kinds, UTF-8 byte spans, and deterministic
error-recovery diagnostics. Persisted Python artifacts are extracted through
this package-owned Tree-sitter adapter and then normalized by Codira's existing
artifact contract.

## Target compatibility matrix

The bundled `tree-sitter-python-0.25.0` grammar is tested against one explicit
fixture for every advertised Python target minor from 3.8 through 3.14.  The
fixtures are source data, rather than importable modules, so the Python 3.13
Codira host also verifies newer target syntax (including the Python 3.14
template-string fixture).

When upgrading the grammar:

1. confirm the new grammar identity and its supported Python maximum;
2. add or update the fixture for every newly advertised target minor;
3. update the tested-minor and grammar-maximum capability metadata together;
4. retain an invalid-syntax fixture and verify partial analysis still withholds
   structural artifacts; and
5. run the package matrix tests and the repository validation gate.

Repository-local editable install:

```bash
source .venv/bin/activate
pip install -e ../codira
pip install -e ../codira/packages/codira-analyzer-python
```

After installation, verify discovery with:

```bash
codira plugins
codira cov
```

Package-local verification:

```bash
pytest -q packages/codira-analyzer-python/tests
```
