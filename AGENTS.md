# AGENTS.md — Codira

## Repository map

| Path | Purpose |
| --- | --- |
| `src/codira/` | Core library and CLI |
| `packages/` | First-party plugins and bundle metadata |
| `tests/` | Behavioral and contract validation |
| `docs/` | Documentation, architecture, ADRs |
| `scripts/` | Development and process tooling |
| `.artifacts/` | Generated measurement artifacts |
| `benchmarks/` | Measurement-campaign manifests |

The core pipeline is `CLI → indexer → query → analyzer → tests`. Keep scanner,
indexer, query, and CLI responsibilities separate. Plugins are independently
distributed extensions discovered through `registry.py`; do not move their logic
into the core without an explicit architectural decision. `schema.py` defines
logical metadata, not backend DDL.

For repository orientation and code exploration, use tools in this order:

1. Codira MCP server;
2. `codira` command-line interface;
3. `rg` only when both Codira interfaces are unavailable, insufficient, or
   irrelevant.

Use the selected Codira interface to index and narrow the investigation before
reading implementation details. High-value entry points are `cli.py`,
`indexer.py`, `query/`, the relevant analyzer, then tests.

## Package and architecture constraints

- First-party plugins are under `packages/`, including analyzers, structural
  backends, vector stores, embeddings, and `codira-bundle-official`.
- Tests may contain full non-production implementations, including an in-memory
  backend; they are authoritative for behavior.
- Preserve logical schema/backend boundaries and do not bypass established
  abstractions or duplicate cross-layer logic.
- Generated artifacts must be changed through their generator and regenerated.
- Use `uv` for the environment; plugins may be installed through entry points
  outside this checkout.

## Validation

```bash
uv run python scripts/validate_repo.py
```

If the primary gate cannot run, report why and use the closest repository-local
fallback. Commit scopes and release/version rules are defined by the repository
hooks and documentation.
