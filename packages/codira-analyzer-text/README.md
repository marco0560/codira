# codira-analyzer-text

First-party plain-text documentation analyzer for `codira`.

This package emits documentation artifacts for narrowly scoped `.txt`
documentation files. It intentionally ignores arbitrary text fixtures, logs,
generated outputs, and vendor material.

```bash
pytest -q packages/codira-analyzer-text/tests
```
