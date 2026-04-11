# ADR-008 — Batched embedding generation and tunable inference runtime

**Date:** 02/04/2026
**Status:** Accepted

## Context

`ADR-005` accepted real persisted embeddings as a first-class indexing artifact.
That decision established correctness and deterministic reuse, but the current
indexing path still computes embeddings one row at a time:

* `_flush_embedding_rows()` recomputes vectors per pending row
* `embed_text()` calls `SentenceTransformer.encode([text], ...)` for one text
  at a time
* repeated semantic payloads within one indexing run are encoded repeatedly
* operators lack a repository-native benchmark tool for phase-level indexing
  diagnostics

Real workloads now show that this architecture leaves substantial throughput on
the table during `codira index --full`, especially on repositories with many
embedding-bearing symbols.

The performance work must preserve these invariants:

* persisted vectors remain deterministic
* existing embedding invalidation rules remain unchanged
* row insertion order remains deterministic
* retrieval semantics do not silently change
* runtime tuning stays explicit and operator-controlled

## Decision

Adopt batched embedding generation for indexing together with explicit runtime
tuning controls and a repository-native benchmark helper.

### Batched Index-Time Embeddings

`codira` will introduce a batched embedding API that accepts multiple texts
at once and returns vectors in the same order.

Index-time persistence will:

* keep deterministic row ordering
* group recomputed payloads into batches
* preserve row-level reporting for reused versus recomputed embeddings
* continue to reuse persisted vectors when stable identity and content hash
  match

### Same-Run Payload Deduplication

During one embedding flush, `codira` will encode each unique semantic
payload at most once.

Rows with identical embedding payload text will reuse the same serialized
vector in memory before insertion. This optimization is local to one run and
does not alter the persisted invalidation contract.

### Explicit Runtime Tuning Surface

The embedding backend will expose environment-driven runtime controls for:

* embedding batch size
* sentence-transformers device selection
* optional Torch thread counts

These controls remain explicit. They do not introduce background adaptation or
host-specific heuristics.

Operators can override these values explicitly through environment variables
when a given host performs better with different settings.

### Benchmark Script

The repository will provide a dedicated benchmark script that times major index
phases and reports embedding batch behavior in structured JSON.

This script is a diagnostics tool. It does not change normal CLI output or
index semantics.

## Consequences

### Positive

* indexing can use the embedding backend more efficiently
* duplicate embedding payloads no longer force duplicate model work in the same
  flush
* operators can benchmark indexing phases without invasive local patching
* future GPU or ONNX work has a stable instrumentation baseline

### Negative

* embedding code paths become more complex than the previous one-row loop
* new tuning controls increase the supported runtime surface area
* batch-level bugs could misassociate vectors with rows if ordering discipline
  is broken

### Neutral / Trade-offs

* row-level `embeddings_recomputed` accounting remains stable even when the
  same-run payload cache avoids a second model call
* runtime tuning remains opt-in so behavior stays conservative by default
* query-time embedding stays on the single-text wrapper and benefits from the
  shared batched backend implementation indirectly

## Execution Rules

* Use the dedicated branch `feat/batch-embedding-indexing`.
* Keep the execution ledger current as work lands.
* Land deterministic benchmark coverage before tuning larger runtime changes.
* Preserve validation coverage for embeddings and indexing behavior.

## Phase Ledger

* [x] Phase 1 — Branch bootstrap and execution ledger
* [x] Phase 2 — ADR and benchmark scope
* [x] Phase 3 — Batched embedding backend API
* [x] Phase 4 — Same-run payload deduplication in index persistence
* [x] Phase 5 — Benchmark tooling and documentation
* [x] Phase 6 — Validation, tuning review, and merge preparation
