# ADR-026 — Repository-local warm query daemon

**Date:** 08/08/2026
**Status:** Accepted

## Context

Repeated direct queries repeatedly load plugins, embedding models, and backend
connections. The existing optional daemon owns automatic indexing and must
remain the sole automatic index writer. A process that serves cached results
would make the persistent SQLite or DuckDB index non-authoritative.

## Decision

Codira will add one optional warm query daemon per resolved repository root
and effective output directory. It is fixed to that identity at startup,
serves multiple local MCP and CLI clients, never accepts arbitrary repository
paths, never indexes files, and never mutates the index.

T1: query execution is serialized through one connection-owning worker in v1.
H1: index coordination publishes durable generations before and after backend
mutation, and a query daemon atomically replaces a fully warmed session only
after observing a ready generation. F1: CLI and MCP use the daemon
opportunistically and retry through direct-core execution when unavailable.
N1: there is no production in-memory backend or final-result cache.

The contract preserves the boundary with #51: no repository catalogue,
cross-repository routing, or request-path selection is introduced here.

## Consequences

The initial slice provides disabled-by-default configuration, service identity
and lifecycle/status types, capability reporting, and reserved CLI commands.
It starts no daemon. Later slices add durable index-generation publication,
warm sessions, authenticated local IPC, lifecycle adapters, MCP/CLI routing,
and performance validation.
