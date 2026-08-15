# Local MCP quickstart

Codira exposes local, read-only repository intelligence through a standard-input/output MCP server. The selected repository is fixed when the server starts; MCP requests never accept repository paths.

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
