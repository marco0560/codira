# Backend Plugins

Backend plugins must return an object implementing
`codira.contracts.IndexBackend`.

The smallest working example lives at
`examples/plugins/codira_demo_backend`.

Backends are different from analyzers:

- exactly one backend is active for one repository instance
- the backend is selected by name through `CODIRA_INDEX_BACKEND`
- analyzers can be many; backends are singular

Register a backend:

```toml
[project.entry-points."codira.backends"]
demo = "codira_demo_backend:build_backend"
```

Select it:

```bash
export CODIRA_INDEX_BACKEND=demo
codira index
```

Rules:

- backend names must be unique across built-ins and external plugins
- duplicate names are rejected deterministically
- unsupported backend names fail fast before indexing or query work
- backend plugins must not perform language parsing

Pragmatic recommendation:

- start by wrapping or adapting existing storage behavior
- only then introduce a fully independent persistence implementation

## First-Party Backends

Current first-party backends:

- `sqlite`
- `duckdb`

Activation is environment-based:

```bash
export CODIRA_INDEX_BACKEND=duckdb
codira index
```

The default remains `sqlite` when `CODIRA_INDEX_BACKEND` is unset.

Operator notes:

- one backend is active for one repository instance
- backend packages are installed through `pip`
- unsupported backend names fail fast with an installation hint when a
  first-party backend package exists

DuckDB guidance:

- install `codira-backend-duckdb` through `pip`
- use DuckDB when you want a local file-backed backend that scales better for
  larger analytical or document-heavy repository indexes
- prefer it over a service database when the repository remains a local
  single-operator or single-workspace workflow
