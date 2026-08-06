# ADR-025 — Optional deterministic daemon mode

**Date:** 06/08/2026
**Status:** Accepted

## Context

Codira indexes repositories explicitly through `codira index`. Users need an
optional automatic mode without turning time-dependent background state into a
correctness dependency for query commands.

## Decision

Codira will expose an optional daemon contract. It will use a cross-platform
watcher behind a Codira-owned interface, coalesce events, and run the existing
incremental indexing planner under shared mutation coordination. Explicit
indexing remains authoritative and uses the same coordination boundary.

The public lifecycle is `run`, `install`, `uninstall`, `start`, `stop`, and
`status`. Systemd, launchd, and Windows Service Control Manager adapters are
part of the intended implementation. Daemon configuration is explicit,
disabled by default, and limited to enablement, debounce timing, and
repo-relative watch scope.

One working-tree index is authoritative. The daemon records the Git `HEAD`
that its most recent completed reconciliation observed. A changed `HEAD`
schedules one debounced incremental `index_repo()` pass: hash-identical files
are reused while changed, new, and deleted paths are reconciled. Codira does
not maintain separate per-branch or per-commit index snapshots.

## Consequences

The initial slice records configuration and command contracts only; it does
not start processes, install services, or watch files. Subsequent slices must
make daemon state observable, preserve deterministic reconciliation after
event loss or branch changes, and test service adapters without installing host
services.

All index mutations share the advisory lock owned by the public
`index_repo()` coordinator. Explicit indexing keeps the lock through backend
initialization and Git metadata persistence; nested callers can safely retain
the same lock while rechecking freshness. A future daemon invokes that same
public coordinator rather than introducing a second write path.
