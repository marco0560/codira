# Quick Start

The smallest plugin package needs:

1. a normal Python package
2. a dependency on `codira`
3. one entry point in either `codira.analyzers` or `codira.backends`
4. a zero-argument callable that returns a plugin instance

If you want a copyable starting point instead of writing from scratch, begin
with one of these example packages:

- `examples/plugins/codira_demo_analyzer`
- `examples/plugins/codira_demo_backend`

Minimal analyzer package skeleton:

```toml
[project]
name = "codira-demo-analyzer"
version = "0.1.0"
dependencies = ["codira"]

[project.entry-points."codira.analyzers"]
demo = "codira_demo_analyzer:build_analyzer"
```

Minimal backend package skeleton:

```toml
[project]
name = "codira-demo-backend"
version = "0.1.0"
dependencies = ["codira"]

[project.entry-points."codira.backends"]
demo = "codira_demo_backend:build_backend"
```

After installation:

```bash
pip install -e /path/to/your/plugin
codira plugins
codira cov
```

Backend plugins also need explicit activation:

```bash
export CODIRA_INDEX_BACKEND=your-backend-name
codira index
```

For the first-party DuckDB backend:

```bash
pip install codira-backend-duckdb
export CODIRA_INDEX_BACKEND=duckdb
codira index
```

If discovery fails, `codira plugins` shows whether the plugin was:

- loaded
- skipped
- rejected as a duplicate

Use `codira cov` to verify whether the current analyzer set fully
covers tracked files under `src/`, `tests/`, and `scripts/`. If you want to
block partial indexing runs, use:

```bash
codira index --require-full-coverage
```
