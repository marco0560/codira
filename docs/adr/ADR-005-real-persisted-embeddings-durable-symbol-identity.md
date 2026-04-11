# ADR-005 — Real persisted embeddings with durable symbol identity

**Date:** 29/03/2026
**Status:** Accepted

## Context

Issue `#1` asks `codira` to move from its current placeholder local
embedding backend to real persisted embeddings while preserving the explicit
manual indexing model.

The repository already persists semantic artifacts in SQLite and already uses
explicit invalidation when the embedding backend version changes. That is not
yet sufficient for efficient reuse within a changed file:

* unchanged files can already reuse all stored embeddings
* changed files currently force regeneration of all symbol embeddings owned by
  the file
* small local edits therefore discard many still-valid symbol embeddings

The root cause is architectural rather than model-specific:

* embedding rows are tied to transient symbol-row identifiers
* the analyzer border contract does not expose a durable symbol identity
* the indexer cannot diff old and new semantic units within one changed file

The issue therefore requires two linked changes rather than only a backend
swap:

* replace the placeholder embedding backend with a real local backend
* extend analyzer output with durable symbol identity so symbol-level reuse
  becomes deterministic

The solution must still preserve these invariants:

* indexing remains explicit through `codira index`
* no background indexing or query-time mutation is introduced
* embeddings are invalidated when semantic input changes
* embeddings are invalidated when backend or backend-version metadata changes
* contributor-facing contracts, docs, and tests remain first-class

## Decision

Adopt a real persisted embedding path together with analyzer-owned durable
symbol identity.

### Real Embedding Backend

`codira` will replace the current placeholder hash backend with a real
local embedding backend.

The active backend contract will continue to expose explicit metadata used for
deterministic invalidation:

* backend name
* backend version
* embedding dimension
* any fixed model identity required by the chosen backend contract

The dependency stack and local model provisioning rules will be documented
explicitly. Indexing must fail fast when the configured backend cannot be used
locally; implicit remote APIs or hidden background downloads are out of scope.

### Durable Symbol Identity at the Analyzer Boundary

The analyzer contract will evolve so normalized artifacts carry a stable
symbol identity produced by the analyzer itself.

That identity must be:

* deterministic
* language-aware
* independent of transient database row ids
* independent of source line numbers and parse-node byte offsets
* stable under unrelated edits elsewhere in the file
* changed when the symbol's semantic identity changes

This contract extension belongs at the analyzer boundary rather than inside
the backend because only analyzers have the language-specific knowledge needed
to define symbol sameness correctly.

### Symbol-Level Reuse for Changed Files

When a file changes, the indexer will no longer treat the file as an
all-or-nothing embedding unit.

Instead, for that file it will:

* compare the old persisted stable-id set with the new analyzer output
* delete symbols present only in the old set
* insert symbols present only in the new set
* reuse stored vectors for symbols whose stable identity and semantic payload
  hash are unchanged
* recompute embeddings only for symbols whose semantic payload changed or
  whose backend metadata no longer matches

This preserves determinism while avoiding unnecessary regeneration for large
files with small edits.

### Storage Strategy

The storage schema will persist:

* stable symbol identity for indexed symbols
* content hashes for the exact embedding text payloads
* backend metadata required for deterministic invalidation
* embedding vectors as binary float32 payloads

The existing explicit indexing model remains unchanged:

* embeddings are computed only during indexing
* queries read persisted vectors only
* no background service is introduced

## Consequences

### Positive

* real embeddings become a durable indexed artifact rather than a placeholder
  semantic channel
* changed files can preserve unchanged symbol embeddings deterministically
* symbol disappearance and rename handling become explicit set-diff operations
  rather than side effects of file-wide replacement
* the analyzer/backend separation remains intact because the language-aware
  identity logic lives in analyzer output
* future analyzers can participate in symbol-level reuse by implementing the
  same stable-id contract

### Negative

* the analyzer contract becomes stricter and existing analyzers and analyzer
  tests must be updated
* schema and persistence logic become more involved than the current
  file-scoped replacement model
* dependency management and local model provisioning add operator overhead

### Neutral / Trade-offs

* the first implementation may still delete and recreate non-semantic
  file-owned rows while preserving embeddings through stable-id reuse
* stable identity is intentionally semantic rather than source-location-based,
  so symbol moves within a file do not imply invalidation by themselves
* later work may further optimize candidate selection or partial persistence,
  but that is not required to establish the contract

## Execution Rules

* Use the dedicated issue branch `issue/1-real-embeddings`.
* Keep the execution ledger current as work lands.
* Make multiple commits, with at least one commit per phase.
* Split large phases into smaller atomic commits when needed.
* Keep tests, docstrings, and documentation in scope for every phase.
* Merge back to `main` with a squash commit that closes issue `#1`.

## Phase Ledger

Mark each phase as work lands.

* [x] Phase 1 — Branch bootstrap and execution scaffold
* [x] Phase 2 — ADR and execution ledger
* [x] Phase 3 — Dependency and local-model provisioning updates
* [x] Phase 4 — Analyzer contract extension for durable symbol identity
* [x] Phase 5 — Built-in analyzer stable-id implementation
* [x] Phase 6 — Schema and storage migration for stable symbol reuse
* [x] Phase 7 — Symbol-level reuse and invalidation in indexing
* [x] Phase 8 — Real embedding backend integration
* [x] Phase 9 — Query, explain, and inventory updates
* [x] Phase 10 — Tests, docs, and merge preparation

## Decision

<Describe the decision>

## Consequences

<Describe the consequences>
