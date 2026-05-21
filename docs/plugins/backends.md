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

Package-boundary rule:

- backend-specific helper modules belong inside the backend package
- core compatibility shims, when temporarily required, must remain import-only
- cross-backend runtime imports are migration debt and should be localized or
  removed as soon as parity allows

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

Current implementation note:

- DuckDB now owns its persistence helper implementation locally
- DuckDB no longer imports the SQLite backend package at runtime
- DuckDB owns its query and maintenance implementation locally inside the
  backend package

## Read And Write Responsibilities

Backend plugins now have two distinct responsibilities:

- `IndexBackend` for read-heavy operations
- `IndexWriteSession` for mutation-heavy indexing work

Backends should keep these read-side operations cheap:

- runtime inventory reads
- analyzer inventory reads
- file-hash and analyzer-ownership reads
- embedding-compatibility checks
- normal query commands such as `ctx`, `sym`, `calls`, `symlist`, and `audit`
- warm-index maintenance detection

Backends should keep mutation-side work behind `begin_index_session(root)`:

- stale-maintenance cleanup
- full or incremental storage preparation
- analyzed-file persistence
- derived-index rebuilds
- runtime inventory writes
- commit, abort, and close

DuckDB-specific guidance:

- ordinary `open_connection()` calls must stay read-oriented
- schema repair or migration work must not run during normal query opens
- writer setup belongs in the write session, not in the query path
