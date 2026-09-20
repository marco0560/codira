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
- Before a paid OpenRouter completion, verify the exact selected models through
  authenticated `/models/user`, not only the public catalog. Preserve the
  key-visible reasoning contract; never send `reasoning.enabled: false` to a
  model marked as mandatory-reasoning.
- Persist the exact received provider response in the ignored, per-attempt
  artifact before semantic validation. A parsing failure must retain its
  response evidence and digest in terminal state, never discard it or place it
  in logs, tracked files, credentials, or request headers.
- Create paid agent-efficiency work only with
  `scripts/generate_agent_efficiency_campaign.py` from a versioned
  `campaign-spec` JSON file. The factory, offline validation, authenticated
  preflight, and paid tmux execution are separate stages. Never hand-author a
  campaign manifest or ad-hoc launch command; preserve the factory's immutable
  manifest and launch-plan artifacts, and do not reuse their output directory.

## Validation

```bash
uv run python scripts/validate_repo.py
```

Run the full gate in a tmux session with a durable log and separately written
exit-status file. Wait at least three minutes before the first status check,
then poll no more often than once per minute. When a successful gate has
finished, leave its completed session and evidence intact; do not terminate it
merely as cleanup.

If the primary gate cannot run, report why and use the closest repository-local
fallback. Commit scopes and release/version rules are defined by the repository
hooks and documentation.

For a full gate expected to exceed foreground observation, run it in a named
tmux session with a durable log, then capture its terminal exit status before
reporting the result. Do not restart an already-confirmed live gate merely to
move it under tmux; preserve and report that existing terminal record.
