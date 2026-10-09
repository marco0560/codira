# Local repository families

A family is a versioned TOML file selected explicitly by the operator. It
references registered workspace names, optional descriptive roles, and optional
directed cross-repository references. Keep the file in a project repository or
your persistent configuration directory. The manifest contains neither index
data nor credentials; portable manifests refer to the same workspace names on
each machine, while each machine's registry owns its actual paths.

Each member keeps its independent repository root, configuration, backend, and
state directory. Existing `codira index --workspace NAME`, `codira ctx
--workspace NAME`, and `codira-mcp --workspace NAME` continue to work autonomously.
Family operations aggregate those indexes without copying repository facts into
a new database. SQLite and DuckDB members can coexist.

## Define and index a family

Prerequisites: a Codira host installation with the analyzers and backends needed
by its members. Run these commands from any directory in that host environment;
from the Codira development checkout, prefix them with `uv run`.
Replace `/absolute/path/to/core`, `/absolute/path/to/plugin`, and
`/absolute/path/to/codira-family.toml` with persistent paths on your machine.

```bash
codira workspace add core --path /absolute/path/to/core
codira workspace add plugin --path /absolute/path/to/plugin
```

Create `/absolute/path/to/codira-family.toml`:

```toml
schema_version = 1
name = "my-system"

[[members]]
workspace = "core"
role = "core"

[[members]]
workspace = "plugin"
role = "plugin"
```

Workspace identities, canonical repository roots, and effective index-state
directories must be distinct; members must be explicitly registered. Roles are
descriptive; they do not boost ranking. Unknown keys, unsupported versions,
unsafe identities, and empty membership are rejected.

```bash
codira family index /absolute/path/to/codira-family.toml --json
codira family status /absolute/path/to/codira-family.toml --json
codira family validate /absolute/path/to/codira-family.toml --json
```

Indexing attempts every member in name order and retains each successful index.
It returns a per-member index report and exit status, and exits nonzero when any
member fails or produces an unusable/partial index. There is no cross-repository
transaction. `--full`, `--defer-embeddings`, and `--require-full-coverage` reuse
the existing index options; `--defer-embeddings` requires embeddings to be
enabled in every member's effective configuration.

Status reports every member's readiness; validation additionally resolves all
declared links and exits nonzero for unavailable members. Recover from failure
by fixing the reported workspace registration, configuration, or source error
and rerunning `family index`. Successful member indexes remain available.

## Query across members

```bash
codira family ctx /absolute/path/to/codira-family.toml "plugin registration" --json
codira family sym /absolute/path/to/codira-family.toml register_plugin --json
codira family sym /absolute/path/to/codira-family.toml register_plugin --member core --json
```

All family commands print structured JSON, retaining complete evidence and
repository origin. Each discovery item has `repository`, `role`, a
repository-relative `file`, and a family-qualified identity when it represents
a symbol. Identically named symbols in different members remain distinct.
Expand an identity using `codira family evidence MANIFEST IDENTITY`.

Context results use `1 / (60 + member_rank)` to merge independently ranked
candidate lists. Member scores and ranks remain visible for inspection; raw
scores from different repositories are not treated as comparable. Each
repository-qualified candidate belongs to its own member list, so equal local
ranks tie across members. Ties resolve by workspace name and source identity,
independently of manifest member order. This is deterministic federation, not
cross-repository semantic score calibration.

`--limit` sets the global whole-item page size, from 1 to 100. Copy
`page.next_cursor` exactly into `--cursor` for continuation. The cursor binds
the manifest, resolved workspace routing, effective configurations, query,
filter, runtime identity, candidate results, and every member's generation.
Any change invalidates it; restart from the first page. Member retrieval uses
its existing candidate coverage and limits; the family does not invent new
facts or expand analyzer coverage.

Queries fail strictly when a selected member is missing, updating, failed,
empty, partially indexed, incompatible with the current runtime, or stale
against its source files. Queries do not index automatically. Use
`--allow-partial` explicitly to return available results with `status =
"partial"` and per-member exclusion reasons. `--member` can be repeated to
select declared workspaces. Unselected unavailable members do not fail filtered
queries, but their state still participates in cursor invalidation.

## Explicit cross-repository references

Append directed links with exact persisted symbol names and definition
locations. Replace the sample names, paths, and line numbers with indexed facts:

```toml
[[links]]
source = {workspace = "plugin", name = "caller", file = "sample.py", lineno = 4}
target = {workspace = "core", name = "helper", file = "sample.py", lineno = 1}
```

```bash
codira family refs /absolute/path/to/codira-family.toml caller --direction outgoing --json
codira family refs /absolute/path/to/codira-family.toml helper --direction incoming --json
```

Both endpoints must resolve uniquely in their declared repositories. Responses
label these edges `provenance = "family_manifest"`; operator declarations are
not analyzer-discovered calls. Family references traverse these explicit links
only. Use existing per-repository `refs` and `calls` for analyzer-discovered
local relationships. Matching names never create a cross-repository edge.
Moving a definition requires updating its manifest location. Partial mode
excludes unresolved links and records their reasons.

## MCP startup

```bash
codira-mcp --family /absolute/path/to/codira-family.toml
```

For a Codex client, configure:

```toml
[mcp_servers.codira]
command = "codira-mcp"
args = ["--family", "/absolute/path/to/codira-family.toml"]
```

`--family`, `--workspace`, and `--root` are mutually exclusive. The manifest
and workspace routing are resolved once at startup. Restart the server after
editing the manifest or registry; index readiness and generations are checked
on each query. MCP exposes read-only `capabilities`, `index_status`,
`context_for_task`, `symbol`, `references`, and `symbol_evidence`. Call
`capabilities` for exact schemas and declared member names. Query tools accept
`repositories` as a list of those names and explicit `allow_partial`; requests
never select new families or supply filesystem roots.

The initial implementation runs direct member queries and verifies source hashes
before and after retrieval. This favors correctness over warm-query latency;
shared hosting, remote orchestration, and automatic discovery remain outside
this feature. See [ADR-033](adr/ADR-033-local-family-federation.md).
