# Local MCP quickstart

Codira exposes local, read-only repository intelligence through a standard-input/output MCP server. The selected repository is fixed when the server starts; MCP requests never accept repository paths.

## Start in under five minutes

From the repository you want to inspect, build its local index and generate a client configuration:

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

All three presets launch `codira-mcp --root /path/to/repository`. The server is local and read-only; it has no network transport, shell tool, or repository-path request parameter.

## Verify the server directly

```bash
uv run codira-mcp --root "$PWD"
```

MCP clients manage the stdio session themselves. Use the generated configuration instead of starting the server manually during normal client use.
