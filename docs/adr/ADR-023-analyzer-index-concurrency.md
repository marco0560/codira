# ADR-023 — Analyzer-side index concurrency

## Status

Accepted.

## Decision

Codira parallelizes only the per-file analyzer phase. Core owns scheduling,
workers construct configured analyzer instances independently, and results are
merged in planned path order. Process workers are the automatic preference;
thread workers require an explicit reentrancy declaration.

All persistence remains parent-owned. Incremental runs retain one
`IndexWriteSession`, while full bulk backends retain their existing single
backend-owned transaction. Analyzer declarations are exported by `codira caps
--json` and missing declarations fail closed for explicit concurrent modes.

## Consequences

The index remains deterministic across serial and concurrent runs while
third-party plugins stay serial until they publish a verified declaration.
Backend write concurrency remains outside this decision and belongs to issue
#56.
