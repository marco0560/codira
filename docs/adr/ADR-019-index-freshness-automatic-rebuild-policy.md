# ADR-019 — Index Freshness and Automatic Rebuild Policy

**Date:** 24/04/2026
**Status:** Accepted

## Context

The CLI does not treat read/query commands as purely passive when the local
index is missing or stale.

Evidence:

- `src/codira/cli.py` documents that if the on-disk index is missing or stale,
  `_ensure_index()` rebuilds it automatically and refreshes Git commit metadata.
- Query subcommands such as `sym`, `emb`, `calls`, `refs`, `audit`, and `ctx`
  call `_ensure_index()` before reading indexed data.
- `src/codira/storage.py` stores repository-local state under `.codira`,
  including `index.db`, `metadata.json`, and `index.lock`.
- `src/codira/cli.py` checks schema version, Git commit, and indexed-file count
  to decide whether a rebuild is required.

This behavior affects the user-facing contract because commands that appear to
read context may create or mutate repository-local index state.

## Decision

Treat automatic index freshness repair as accepted CLI behavior for
index-backed read/query commands.

When the index is missing, stale, or schema-incompatible, the CLI may rebuild
the index before serving a query. Rebuild decisions must remain deterministic
and grounded in explicit metadata such as schema version, Git commit, and
indexed file counts.

If automatic rebuild fails, the CLI must surface an operator-facing error and
manual remediation command instead of silently returning stale or partial
results.

## Consequences

### Positive

- Query commands can recover from missing or stale local indexes.
- Users receive fresh results without manually running `codira index` for every
  repository change.
- Freshness checks are tied to explicit metadata rather than hidden state.

### Negative

- Read/query commands may perform index writes and embedding work.
- Query latency can include rebuild cost.
- Read-only filesystems require explicit output-root handling.

### Neutral / Trade-offs

- This policy preserves deterministic behavior, but it makes `.codira` state
  mutation part of the query-command contract.
