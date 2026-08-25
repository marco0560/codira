# Local MCP quickstart

Codira exposes local, read-only repository intelligence through a standard-input/output MCP server. The selected repository is fixed when the server starts; MCP requests never accept repository paths.

The `arch` tool returns a bounded, read-only architecture-model snapshot for
the trusted repository. It does not write report files; use `codira arch` when
you need the DOT, Markdown, JSON, or optional SVG artifact set.

`emb` searches stored symbol embeddings and `docs` searches stored
documentation embeddings. Both accept a query, optional repository-relative
`prefix`, and bounded `limit`; neither exposes `emb purge` or any other
vector-store maintenance operation.

## Start in under five minutes

From the repository you want to inspect, build its local index and generate a
client configuration. This is direct-path routing; the Codira host runtime can
live in a separate environment from the repository:

```bash
uv run codira index
uv run codira-mcp-config codex --root "$PWD"
```

Copy the generated block into the matching client configuration file, restart the client, then ask: `What symbols implement the index command?` The server provides a useful structured answer through `symbol`, `symbols`, or `context_for_task`.

## Supported presets

The generator prints the configuration by default, or writes an explicit output path:

```bash
uv run codira-mcp-config claude-desktop --root /path/to/repository --output claude_desktop_config.json
uv run codira-mcp-config codex --root /path/to/repository --output config.toml
uv run codira-mcp-config cursor --root /path/to/repository --output mcp.json
```

All three presets launch `codira-mcp --root /path/to/repository`. The server is
local and read-only; it has no network transport, shell tool, or
repository-path request parameter.

## Named workspace startup

For a persistent host installation, register the target once and start MCP by
workspace name. The workspace fixes the target repository, Codira state root,
and optional configuration file before the server accepts requests:

```bash
codira workspace add sample --path /path/to/repository
codira index --workspace sample
codira-mcp --workspace sample
```

`--workspace` and `--root` are mutually exclusive. A live MCP process never
accepts a later path or workspace selector, which keeps its target binding
stable and provenance-safe.

## Parallel repositories

Run one Codex instance per repository with one project-scoped MCP
configuration per instance. Keep a root-bound Codira entry out of the global
`~/.codex/config.toml`; generate and copy this entry into the trusted
repository's `.codex/config.toml` instead:

```bash
cd /path/to/repository-a
codira index
codira-mcp-config codex --root "$PWD"
```

```toml
[mcp_servers.codira]
command = "codira-mcp"
args = ["--root", "/path/to/repository-a"]
```

Repeat for repository B with its own absolute root. Codex starts a separate
STDIO server process for each active configuration. Each process is bound to
its startup root, so it cannot answer requests against another repository.
The default Codira state root is the repository root; therefore separate
repositories also have separate indexes and daemon state by default.

To run automatic indexing and warm reads in each repository, enable the two
independent daemon roles in that repository's `.codira/config.toml`:

```toml
[daemon]
enabled = true

[query_daemon]
enabled = true
```

For foreground development, start both processes from each repository:

```bash
cd /path/to/repository-a
codira daemon run
codira query-daemon run
```

Use `install` followed by `start` in place of `run` to create persistent
per-user services. The indexing daemon is the sole automatic writer. The
query daemon is read-only; compatible MCP processes reuse it, while an absent
or failed daemon causes a direct-core fallback.

### External state roots

When index and daemon state must not live below the repository, use one named
workspace for each repository. A workspace preserves the repository root,
state root, and configuration selection as a single fixed identity:

```bash
codira workspace add repository-a \
  --path /path/to/repository-a \
  --state-root /path/to/codira-state/repository-a \
  --config-file /path/to/repository-a/.codira/config.toml

codira index --workspace repository-a
codira daemon --workspace repository-a run
codira query-daemon --workspace repository-a run
```

Configure the corresponding project-scoped MCP entry with
`args = ["--workspace", "repository-a"]`. Repeat with different workspace
names and state roots for all other repositories. Never share an
`--output-dir`/state root across repositories: endpoint metadata, credentials,
indexes, and daemon lifecycle records are scoped there. Use `--execution-mode`
on an eligible read to verify routing: `warm`, `direct`, or `fallback` is
reported on standard error.

## Verify the server directly

```bash
uv run codira-mcp --root "$PWD"
```

MCP clients manage the stdio session themselves. Use the generated configuration instead of starting the server manually during normal client use.

## Optional warm query daemon

`codira-mcp` always remains usable without a query daemon. At startup it binds
only the supplied trusted root and discovers the matching local endpoint below
that root's effective output directory; it never starts, installs, or selects
another repository service. When the authenticated endpoint has the matching
root identity and protocol, every approved read-only tool is routed through the
warm daemon. Otherwise the existing direct-core adapter is used.

Each response includes credential-free `provenance.execution_mode`:

- `warm` identifies a daemon response and reports its index `generation`.
- `direct` means no compatible daemon was available.
- `fallback` means the daemon request failed and was retried once directly.

This preserves output and pagination semantics while making failures
non-blocking. Multiple MCP processes for one repository can share its one
daemon; another repository or output directory has a distinct identity and is
rejected before connection.
